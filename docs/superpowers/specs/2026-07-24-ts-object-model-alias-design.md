# ts-object-model-alias — Column Alias Management

## Context

ThoughtSpot column aliases enable context-specific display names on Model columns.
Three use cases, all sharing the same TML structure:

1. **Language localization** — translate existing model column names to other
   languages. All users with locale de-DE see "Umsatz" for "Revenue". No
   org/group scoping. AI translation is applicable here.

2. **Tenant-based renaming** — map generic or technical column names to
   business-friendly names per org or group, regardless of language. E.g.
   `string_1` → "Region" for Org 1, "Client Name" for Org 2. No locale
   dimension — locale is `TS_WILDCARD_ALL`. Source is always file or DB
   (AI cannot know org-specific business terminology).

3. **Tenant + locale** — layer language translation on top of tenant renaming,
   with different locale coverage per org. E.g. Org 1 has en/de/fr so "Region"
   → "Région" (fr-FR), while Org 2 has en/es so "Client Name" → "Nombre del
   Cliente" (es-ES). Source is file or DB (the DB table carries the full matrix
   of which orgs have which locales).

These three tiers compose in the same TML `column_alias` document. The scoping
key is always `(column, locale, org, group)` — the difference is which parts
are wildcarded (`TS_WILDCARD_ALL`) vs specific.

Today all three are manual: export a CSV, translate/rename externally, upload via
the UI. This skill automates the full pipeline — export, translate/rename, merge,
import — and exposes each step as a composable `ts alias` CLI command so the
workflow can run interactively (agent) or as a scheduled job (ts-cli pipeline).

### Source applicability by use case

| Use case | AI | File | DB | AI + DB/File |
|---|---|---|---|---|
| 1. Language localization | Yes | Yes | Yes | — |
| 2. Tenant renaming | No — business-specific | Yes | Yes | — |
| 3. Tenant + locale | — | Yes (full matrix) | Yes (full matrix) | Yes — DB/file provides org base names, AI translates to per-org locales |

## Mechanism

Column Aliases via TML (10.13.0.cl Beta, feature-flag gated). The alias TML
document (`column_alias:`) is exported alongside the Model TML when
`export_with_column_aliases: true` is set, and imported via the standard TML import
endpoint. This mechanism supports the full org/group/locale scoping key required
for tenant-based aliasing.

The Manual Translations API (26.7.0.cl) is a separate, org/cluster-scoped system
for translating arbitrary UI strings. It is out of scope for this skill.

## Skill Identity

- **Name:** `ts-object-model-alias`
- **Family:** `ts-object-{type}-{verb}` (family 1)
- **Runtime:** CLI only (no CoCo equivalent — depends on `ts` CLI)

## Command Architecture

### ts-cli command group: `ts alias`

Four composable subcommands. Each reads JSON from stdin and writes JSON (or YAML)
to stdout, so they pipe together.

#### `ts alias export`

Extract model columns and existing aliases.

| Option | Required | Description |
|---|---|---|
| `--model` | Yes | Model GUID |
| `--profile` / `-p` | Yes | ThoughtSpot profile name |

Calls `POST /api/rest/2.0/metadata/tml/export` with
`export_options.export_with_column_aliases: true`. Parses the response and
extracts:

- Model column names, descriptions, and types from the model TML
- Existing `column_alias` TML document (null if none defined)

Output (JSON to stdout):

```json
{
  "model": {"guid": "abc-123", "name": "Sales Model", "fqn": "MODEL_abc123"},
  "columns": [
    {"name": "Revenue", "description": "Total revenue amount", "type": "MEASURE"},
    {"name": "Region", "description": "Sales region", "type": "ATTRIBUTE"}
  ],
  "existing_aliases": {
    "columns": [
      {
        "name": "Revenue",
        "locales": [
          {"name": "de-DE", "alias": "Umsatz", "description": "Gesamtumsatz",
           "org": "TS_WILDCARD_ALL", "group": "TS_WILDCARD_ALL"}
        ]
      }
    ]
  }
}
```

`existing_aliases` is `null` when the model has no aliases.

#### `ts alias translate`

Generate aliases from one of three sources.

| Option | Required | Description |
|---|---|---|
| `--source` | Yes | `ai`, `file`, or `db` |
| `--locales` | When `--source ai` alone | Comma-separated locale codes (e.g. `de-DE,fr-FR`). For `--source ai`: target locales. For file/db: filter (defaults to all). |
| `--orgs` | No | Comma-separated org names to filter (file/db only). Default: all orgs in the source |
| `--groups` | No | Comma-separated group names to filter (file/db only). Default: all groups in the source |
| `--input` | No | Input file path (default: stdin — the export JSON envelope) |
| `--translator` | No | `claude` or `cortex` (when AI translation is involved; default: `claude`) |
| `--api-key-env` | No | Env var name for Anthropic API key (default: `ANTHROPIC_API_KEY`) |
| `--sf-profile` | No | Snowflake profile (when `--source db`, `--locale-config-table`, or `--translator cortex`) |
| `--table` | No | Fully-qualified Snowflake table (when `--source db`) |
| `--csv` | No | CSV file path (when `--source file`) |
| `--ai-locales` | No | Comma-separated locales for AI translation — simple case, same locales for all orgs. Mutually exclusive with `--locale-config` / `--locale-config-table` |
| `--locale-config` | No | YAML file specifying per-org target locales for AI translation (see Locale Configuration) |
| `--locale-config-table` | No | Fully-qualified Snowflake table specifying per-org target locales (see Locale Configuration) |
| `--init-table` | No | Emit DDL for both the alias table and the locale config table, then exit |

**Source: AI** (use case 1 — language localization) — `--locales` is required.
One LLM call per locale, batching all columns. Prompt sends column names +
descriptions as a JSON array, requests translations, enforces JSON schema
response. Validates returned column set matches input; retries once on
malformed output. Org/group is always `TS_WILDCARD_ALL` — AI does not generate
tenant-specific aliases.

**Source: File** (use cases 1, 2, 3) — reads a CSV (via `--csv <path>`) with
columns: `column_name`, `locale`, `alias`, `description`, `org_name`,
`group_name`. `locale`, `org_name`, and `group_name` default to
`TS_WILDCARD_ALL` when empty/omitted. An optional `model_name` column filters
rows for multi-model batch files. The CSV only needs to contain aliases to add
or update — when `build --merge` is used downstream, existing aliases for
other key combinations are preserved. Use `--orgs` / `--groups` to process a
subset when the file contains 1000s of orgs.

When combined with `--ai-locales`, `--locale-config`, or
`--locale-config-table`: reads base org/group aliases from the CSV, then
AI-translates each org's aliases to its configured target locales. Output
includes both the base entries and the AI-generated locale variants.

**Source: DB** (use cases 1, 2, 3) — queries the standard-schema Snowflake
table filtered by `model_name` and optionally by `--locales`, `--orgs`,
`--groups`. When none of the filters are specified, returns all rows for
the model.

When combined with `--ai-locales`, `--locale-config`, or
`--locale-config-table`: reads base org/group aliases from the DB (rows where
`locale = 'TS_WILDCARD_ALL'`), then AI-translates each org's aliases to its
configured target locales. Output includes both the base entries and the
AI-generated locale variants.

Output (JSON to stdout):

```json
{
  "model": {"guid": "abc-123", "name": "Sales Model"},
  "translations": [
    {"column": "Revenue", "locale": "de-DE", "alias": "Umsatz",
     "description": "Gesamtumsatz",
     "org": "TS_WILDCARD_ALL", "group": "TS_WILDCARD_ALL"}
  ],
  "existing_aliases": { "..." }
}
```

The `existing_aliases` field passes through from the export output so that
`build` can merge without a second API call.

#### `ts alias build`

Assemble the `column_alias` TML YAML from translations.

| Option | Required | Description |
|---|---|---|
| `--input` | No | Translations JSON file (default: stdin) |
| `--merge` | No | Merge new translations with existing aliases (from the JSON envelope) |

Output includes a `tml_size_bytes` field. Emits a warning to stderr when the
TML exceeds 20 MB. Errors with guidance when it exceeds 25 MB (the platform
hard limit — see Scale Constraints).

**Merge algorithm** (effective upsert on top of full-replace API):

```
For each (column, locale, org, group) in new_translations:
    → overwrite in merged set
For each (column, locale, org, group) in existing_aliases:
    → keep if key not in new_translations
Assemble merged column_alias TML
```

Without `--merge`, only the new translations are included (clean replace).

Output: `column_alias` TML YAML to stdout.

```yaml
column_alias:
  model:
    name: "Sales Model"
    fqn: "MODEL_abc123"
  columns:
    - name: "Revenue"
      locales:
        - name: "de-DE"
          orgs:
            - name: "TS_WILDCARD_ALL"
              groups:
                - name: "TS_WILDCARD_ALL"
                  alias: "Umsatz"
                  description: "Gesamtumsatz"
```

#### `ts alias import`

Upload the alias TML to ThoughtSpot.

| Option | Required | Description |
|---|---|---|
| `--model` | Yes | Model GUID (for context/validation) |
| `--profile` / `-p` | Yes | ThoughtSpot profile name |
| `--file` | No | TML file path (default: stdin) |
| `--dry-run` | No | Validate without importing |

Selects sync or async import based on payload size (see Scale Constraints).
Payloads < 5 MB: `POST /api/rest/2.0/metadata/tml/import` (synchronous).
Payloads 5–25 MB: `POST /api/rest/2.0/metadata/tml/async/import` (async —
returns `task_id`, command polls until complete, ~10–15 min for large
payloads). Payloads > 25 MB: error before calling the API.

Output: import result JSON (sync) or final async task status JSON.

### Pipeline Examples

```bash
# Use case 1 — Language localization via AI (ad-hoc)
ts alias export --model <guid> -p prod \
  | ts alias translate --locales de-DE,fr-FR --source ai --translator cortex \
      --sf-profile sf \
  | ts alias build \
  | ts alias import --model <guid> -p prod

# Use case 2 — Tenant renaming from DB (scheduled, all orgs)
#   DB rows: (model, "string_1", TS_WILDCARD_ALL, "Region", ..., "Org 1", TS_WILDCARD_ALL)
#            (model, "string_1", TS_WILDCARD_ALL, "Client Name", ..., "Org 2", TS_WILDCARD_ALL)
ts alias export --model <guid> -p prod \
  | ts alias translate --source db \
      --sf-profile sf --table ANALYTICS.PUBLIC.TS_COLUMN_ALIASES \
  | ts alias build --merge \
  | ts alias import --model <guid> -p prod

# Use case 2 — Process a subset of orgs
ts alias export --model <guid> -p prod \
  | ts alias translate --source db --orgs "Org 1,Org 2" \
      --sf-profile sf --table ANALYTICS.PUBLIC.TS_COLUMN_ALIASES \
  | ts alias build --merge \
  | ts alias import --model <guid> -p prod

# Use case 3 — Tenant + locale: DB has org base names, AI translates
#   Locale config table says Org 1 → de-DE,fr-FR; Org 2 → es-ES,pt-BR
ts alias export --model <guid> -p prod \
  | ts alias translate --source db \
      --sf-profile sf --table ANALYTICS.PUBLIC.TS_COLUMN_ALIASES \
      --locale-config-table ANALYTICS.PUBLIC.TS_ALIAS_LOCALES \
      --translator cortex \
  | ts alias build --merge \
  | ts alias import --model <guid> -p prod

# Use case 3 — Same but with simple flag (all orgs get same locales)
ts alias export --model <guid> -p prod \
  | ts alias translate --source db \
      --sf-profile sf --table ANALYTICS.PUBLIC.TS_COLUMN_ALIASES \
      --ai-locales de-DE,fr-FR --translator cortex \
  | ts alias build --merge \
  | ts alias import --model <guid> -p prod

# Use case 3 — Full matrix already in DB (no AI needed)
#   DB rows carry per-org per-locale entries directly
ts alias export --model <guid> -p prod \
  | ts alias translate --source db \
      --sf-profile sf --table ANALYTICS.PUBLIC.TS_COLUMN_ALIASES \
  | ts alias build --merge \
  | ts alias import --model <guid> -p prod

# Use case 1 — From pre-translated CSV file
ts alias export --model <guid> -p prod \
  | ts alias translate --source file --csv translations.csv \
  | ts alias build --merge \
  | ts alias import --model <guid> -p prod

# Multi-model scheduled loop (any use case)
for guid in $(ts metadata search --type LOGICAL_TABLE \
              --subtype ONE_TO_ONE_LOGICAL -p prod | jq -r '.[].id'); do
  ts alias export --model "$guid" -p prod \
    | ts alias translate --source db \
        --sf-profile sf --table DB.SCHEMA.TS_COLUMN_ALIASES \
    | ts alias build --merge \
    | ts alias import --model "$guid" -p prod
done
```

## Standard DB Table Schema

```sql
CREATE TABLE IF NOT EXISTS TS_COLUMN_ALIASES (
    model_name    VARCHAR NOT NULL,
    column_name   VARCHAR NOT NULL,
    locale        VARCHAR NOT NULL,
    alias         VARCHAR NOT NULL,
    description   VARCHAR,
    org_name      VARCHAR DEFAULT 'TS_WILDCARD_ALL',
    group_name    VARCHAR DEFAULT 'TS_WILDCARD_ALL',
    updated_at    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (model_name, column_name, locale, org_name, group_name)
);
```

The skill provides DDL for both tables via `ts alias translate --init-table`.
The user populates them from their translation management system.

## Locale Configuration (AI Target Locales)

Three ways to tell `translate` which locales AI should generate, from simple
to flexible:

**1. Flag** — `--ai-locales de-DE,fr-FR`

Same locales for all orgs and columns. Good for use case 1 (global language
translation) or simple use case 3 where all orgs share the same locale set.

**2. Config file** — `--locale-config locales.yaml`

```yaml
default: [de-DE, fr-FR, ja-JP]        # baseline — all orgs get these

orgs:
  "Org 1": [de-DE, fr-FR, en-GB]      # Org 1 override
  "Org 2": [es-ES, es-MX, pt-BR]      # Org 2 gets a different set
```

Org-specific entries **replace** the default set (not additive). If Org 2
has entries, it gets exactly those locales, not default + its own. This keeps
the behavior predictable.

**3. DB table** — `--locale-config-table DB.SCHEMA.TS_ALIAS_LOCALES`

```sql
CREATE TABLE IF NOT EXISTS TS_ALIAS_LOCALES (
    org_name      VARCHAR DEFAULT '*',
    locale        VARCHAR NOT NULL,
    PRIMARY KEY (org_name, locale)
);
```

Example rows:

```
('*',     'de-DE')    -- default for all orgs
('*',     'fr-FR')    -- default for all orgs
('Org 1', 'de-DE')    -- Org 1 gets de-DE (override)
('Org 1', 'fr-FR')    -- Org 1 gets fr-FR (override)
('Org 1', 'en-GB')    -- Org 1 also gets en-GB
('Org 2', 'es-ES')    -- Org 2 gets es-ES (override)
('Org 2', 'pt-BR')    -- Org 2 gets pt-BR (override)
```

Same override semantics: when an org has its own rows, those replace the
`*` defaults for that org.

**Resolution precedence:** `--ai-locales` flag > `--locale-config` file >
`--locale-config-table`. They are mutually exclusive — use whichever fits
the deployment. The flag is a shorthand for "same locales everywhere."

**Column-level locale targeting** is omitted from v1. The locale config
table schema can take an optional `column_name` column later if a real use
case emerges — but org-level granularity covers the practical cases without
over-engineering.

## AI Translation Design

AI handles **language translation only** — it does not invent org/group-specific
business names. It applies in two scenarios:

- **Use case 1** (`--source ai`): translate the model's base column names
  directly. Org/group = `TS_WILDCARD_ALL`.
- **Use case 3** (`--source db` or `--source file` + locale config): read
  org-specific base aliases from the source, then translate each org's
  alias names to that org's configured target locales. The AI input is the
  org's alias (e.g. "Region" for Org 1), not the raw model column name
  (e.g. `string_1`).

Mechanics:
- One LLM call per (org, locale) combination — all columns for that org
  batched together for token efficiency
- Prompt includes column names (or org-specific aliases), descriptions,
  and the target locale
- Response format: JSON array of `{column, alias, description}` objects
- Claude path: `anthropic.messages.create()` with structured output
- Cortex path: `SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3.1-70b', prompt)`
  via the Snowflake connector
- Guardrails: validate returned column count matches input; validate
  no column names were fabricated; retry once on malformed response

## Supported Locales (27)

```
da-DK  de-DE  de-CH  en-AU  en-CA  en-DE  en-IN  en-NZ  en-GB  en-US
es-ES  es-US  es-MX  fr-CA  fr-FR  ja-JP  ko-KR  it-IT  nb-NO  nl-NL
pt-BR  pt-PT  ru-RU  fi-FI  sv-SE  zh-CN  zh-HANT
```

All three sources validate locale codes against this set.

## Module Layout

| File | Role | I/O |
|---|---|---|
| `ts_cli/alias.py` | Merge logic, TML assembly, CSV/JSON parsing, locale validation | Pure (no I/O) |
| `ts_cli/alias_translate.py` | AI prompt building, response parsing, Cortex SQL generation | Prompt building is pure; API calls are thin I/O |
| `ts_cli/commands/alias.py` | Typer command layer — export/translate/build/import | I/O only |

## Skill Flow (SKILL.md)

```
Step 0  — Overview            Show session plan, confirm ready
Step 1  — Select profile      ts auth whoami to verify ThoughtSpot connection
Step 2  — Select model(s)     Search by name/pattern/connection; confirm selection
Step 3  — Export               ts alias export per model → column count + existing alias summary
Step 4  — Choose use case      (1) Language localization, (2) Tenant renaming, (3) Tenant + locale
Step 5  — Scope aliases        Use case 1: select locales. Use case 2: confirm orgs/groups.
                               Use case 3: confirm org-locale matrix.
Step 6  — Choose source        Use case 1: AI / file / DB. Use cases 2–3: file / DB only.
Step 7  — Generate aliases     ts alias translate → show preview table
Step 8  — Review               User reviews aliases, edits individual entries if needed
Step 9  — Choose mode          Replace (fresh) or Merge (preserve existing aliases)
Step 10 — Build + Import       ts alias build | ts alias import → show result
Step 11 — Verify               Re-export, compare expected vs actual, show summary
```

Steps 3–10 iterate for multiple models. For DB source, the query pulls all
models in one read and partitions per model.

### Multi-Model Selection (Step 2)

- **By name:** `ts metadata search --type LOGICAL_TABLE --subtype ONE_TO_ONE_LOGICAL --name "Sales*"`
- **By GUID list:** user provides explicit GUIDs
- **By connection:** filter models by `dataSourceName`

Each model processes independently. Failures on one model do not block others.
Final summary shows per-model status.

## Error Handling

| Symptom | Action |
|---|---|
| `export_with_column_aliases` returns no alias doc | Normal — model has no existing aliases; proceed with empty set |
| Column alias feature not enabled on instance | Detect via error response; message: "Contact ThoughtSpot to enable the column alias feature" |
| Column name in file/DB not found in model | Warning per column, skip, continue with valid columns |
| Invalid locale code | Error listing the 28 valid codes |
| AI returns malformed JSON | Retry once with stricter prompt; error on second failure |
| AI returns wrong column count | Validate against input; retry with explicit count |
| TML import fails | Show import error; suggest `--dry-run` |
| Snowflake connection fails | Standard `ts-profile-snowflake` error path |
| `--source ai` used with `--orgs`/`--groups` | Error: "AI translation is for language localization only. Use --source file or --source db for org/group aliases" |
| No rows found in DB for model | Error: "No rows in {table} for model_name='{name}'" (with applied filters shown) |
| Org/group name in file/DB not valid in ThoughtSpot | Warning per entry, skip, continue with valid entries |

## Prerequisites

- `ts` CLI
- `ts-profile-thoughtspot` (ThoughtSpot auth)
- Column alias feature flag enabled on the ThoughtSpot instance (Beta, 10.13.0.cl+)
- Optional: `ts-profile-snowflake` (for DB source or Cortex translator)
- Optional: `ANTHROPIC_API_KEY` in env/keychain (for Claude translator)
- Optional: `snowflake-connector-python` (for DB source / Cortex — lazy import)

## Scale Constraints & Import Strategy

### TML upload limit: 25 MB

The ThoughtSpot prism layer enforces a **25 MB hard limit** on TML upload payloads.
Each alias entry in the YAML is ~200 bytes. Practical capacity:

| Scenario | Entries | Size | Fits? |
|---|---|---|---|
| 50 cols × 100 orgs × 1 locale | 5,000 | ~1 MB | Yes |
| 50 cols × 500 orgs × 2 locales | 50,000 | ~10 MB | Yes |
| 50 cols × 1000 orgs × 1 locale | 50,000 | ~10 MB | Yes |
| 50 cols × 1000 orgs × 3 locales | 150,000 | ~30 MB | **No** |

### Full-replace semantics (no partial update until 26.10)

Every TML import replaces all previous alias definitions — there is no partial
update. Each import triggers metadata services (parse, validate, persist,
dependency resolution). **Delta load capability (incremental updates) is
estimated for ThoughtSpot release 26.10.** Until then, every upload must
contain the full alias set.

### Import strategy

The `ts alias import` command uses the following strategy:

1. **Size estimation** — `ts alias build` emits the TML size in its output
   JSON. If the TML exceeds 20 MB, `build` emits a warning to stderr.
   If it exceeds 25 MB, `build` errors with guidance.

2. **Sync vs async** — payloads under 5 MB use the synchronous import
   endpoint (`POST /api/rest/2.0/metadata/tml/import`). Payloads 5–25 MB
   use the async endpoint (`POST /api/rest/2.0/metadata/tml/async/import`)
   which returns a `task_id` and processes in the background (10–15 minutes
   for large payloads). The `import` command polls the async status endpoint
   until completion.

3. **Future: delta load (26.10)** — when ThoughtSpot adds delta load
   support, the `import` command can switch to the incremental endpoint.
   The client-side merge logic (`build --merge`) becomes optional rather
   than required — the API will handle partial updates natively. Track
   the 26.10 release and update the command when available.

### What exceeds 25 MB

If the full alias set exceeds 25 MB (e.g. 50 columns × 1000 orgs × 3
locales), this is a **platform limitation**. Options:

- Reduce locale coverage per org (fewer locales = smaller payload)
- Split across multiple Models (fewer columns per Model)
- Wait for 26.10 delta load support
- Contact ThoughtSpot to discuss raising the limit

The skill documents this constraint clearly and errors before attempting an
import that would fail.

## Scope Exclusions

- Does not translate formula names (ThoughtSpot limitation — aliases are display-name only)
- Does not set user locale preferences (separate concern — `ts users` commands)
- Does not manage the Manual Translations API (separate mechanism, 26.7.0.cl)
- Does not duplicate alias sets across models (DB table is the shared source of truth)

## Verification

Step 11 re-exports the model with aliases and compares:

```
| Column   | Locale        | Org   | Group           | Expected        | Actual          | Status |
|----------|---------------|-------|-----------------|-----------------|-----------------|--------|
| Revenue  | de-DE         | *     | *               | Umsatz          | Umsatz          | OK     |
| string_1 | TS_WILDCARD   | Org 1 | TS_WILDCARD_ALL | Region          | Region          | OK     |
| string_1 | TS_WILDCARD   | Org 2 | TS_WILDCARD_ALL | Client Name     | Client Name     | OK     |
| string_1 | fr-FR         | Org 1 | TS_WILDCARD_ALL | Région          | Région          | OK     |
```

Mismatches or missing entries are flagged. This step confirms the round-trip
succeeded and the aliases are live.
