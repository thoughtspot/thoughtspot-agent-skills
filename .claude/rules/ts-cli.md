# ts-cli Rules

Rules for when to use the `ts` CLI, when to extend it, and when direct API calls
are legitimate exceptions. Applies to both skill authoring and CLI development.

---

## The core rule: Claude skills use `ts`, never `requests`

Claude Code skills (`agents/cli/`) must use `ts` CLI commands for all ThoughtSpot
API calls. Direct `import requests` / `requests.post()` calls in a SKILL.md are an
anti-pattern — they duplicate auth handling, bypass token caching, and break if the
CLI's auth model changes.

```bash
# Correct — CLI handles auth, caching, error formatting
ts tml export {guid} --profile {name} --fqn --associated

# Wrong — direct API call in skill code
requests.post(f"{base_url}/api/rest/2.0/metadata/tml/export", headers=..., json=...)
```

**Exceptions — direct API calls are legitimate in:**
- `references/open-items.md` — self-contained test scripts to verify unverified API behaviour
  before a CLI command is written. These are temporary scaffolding, not skill logic.
- `agents/coco-snowsight/` — CoCo runs inside Snowsight and cannot install or invoke the `ts` CLI.
  CoCo skills use stored procedures (`TS_EXPORT_TML`, `TS_IMPORT_TML`, etc.) instead.

---

## When to add a new command to ts-cli

Add a new `ts` command when **any** of these are true:

- A skill needs an API operation that no existing command covers
- An `open-items.md` test script has been verified against a live instance and is ready
  to become a permanent capability
- Two or more skills would otherwise duplicate the same raw API call

Do NOT add a CLI command speculatively. Wait until a skill actually needs it.

When adding a command, follow the steps in `tools/ts-cli/CLAUDE.md` (Adding a command
section): module in `commands/`, register in `cli.py`, entry in `README.md`, update
the skill that prompted it, add unit tests, bump version in both files.

---

## When a skill needs an API call that ts-cli doesn't have yet

1. Query the SpotterCode MCP for the endpoint spec — `get-rest-api-reference(apiName: "...")`
   if you know the operation ID, otherwise `query: "..."`. Record the canonical request/
   response shape from the spec before writing any code. See `.claude/rules/api-research.md`.
2. Write the call in `references/open-items.md` as a test script — not inline in SKILL.md.
   Reference the MCP finding so the next reader can re-verify.
3. Verify it against a live ThoughtSpot instance; record the finding in open-items.md
4. Add the command to ts-cli (see above)
5. Replace the open-items.md test script reference in SKILL.md with the `ts` command
6. Keep the open-items.md entry until the skill has been tested end-to-end with the new command

Do not ship a skill with inline `requests` calls where a CLI command could exist.

---

## When to migrate an existing direct API call to ts-cli

If a SKILL.md contains `requests.post()` for an operation that ts-cli now supports,
migrate it. The trigger is when:

- A new ts-cli command is added that covers the operation
- The skill is being edited for another reason (opportunistic cleanup)
- The direct call has caused an auth or token expiry bug

Migration is not urgent if the skill is working and untouched, but it is the right
direction. Flag it in a `references/open-items.md` entry if deferring.

---

## ts-cli output conventions

All commands follow these conventions. New commands must match them:

| Convention | Rule |
|---|---|
| Structured data output | JSON to stdout — always, so skills can pipe it |
| Diagnostics / progress | stderr only — never mixed with stdout JSON |
| Auth | Always via `--profile` flag or `TS_PROFILE` env var — never hardcoded |
| Connection identifier | String display name (`connection_name`) — never GUID |
| Pagination | Auto-paginate internally; caller always gets the full result set |

---

## Testing requirements for ts-cli changes

Every new command or modified function needs unit tests in `tools/ts-cli/tests/`.
Tests must not require a live ThoughtSpot connection — test the pure functions
(`_build_table_tml`, `_merge_tables`, etc.) in isolation.

Run before committing any ts-cli change:
```bash
pytest tools/ts-cli/tests/
python tools/validate/check_version_sync.py
```

---

## No v1 endpoints (migration complete — 2026-06-16)

The repo no longer calls any v1 (`/tspublic/v1/...`) endpoint. The last one,
`/tspublic/v1/connection/fetchConnection`, was removed on newer ThoughtSpot Cloud
builds (returns 404) and has been **migrated to the v2 endpoint**
`POST /api/rest/2.0/connection/search` (confirmed via
`get-rest-api-reference(apiName: "searchConnection")`):

- `ts connections get` / `ts connections add-tables` — `_fetch_connection_v2` +
  `_adapt_v2_databases` in `tools/ts-cli/ts_cli/commands/connections.py`
- `connections_get` in `agents/databricks/notebooks/ts_client.py`

**Caveat:** v2 `connection/search` only returns the warehouse database/table/column
hierarchy for connections that authenticate with a stored `SERVICE_ACCOUNT`. OAuth/PKCE
connections return connection metadata with an empty hierarchy (a real ThoughtSpot
limitation, not a CLI bug). To find tables already registered as ThoughtSpot objects,
use `ts metadata search --name "%table%"` and filter on `metadata_header.dataSourceName`
for a connection-scoped result — **do not** rely on connection introspection.

If a new v1 endpoint is ever introduced, migrate it to the v2 equivalent before use:
confirm the v2 spec via `get-rest-api-reference`, update the command/docstring/README,
and bump the version in both `__init__.py` and `pyproject.toml`.
