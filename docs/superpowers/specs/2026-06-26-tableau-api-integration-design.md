# Tableau REST API Integration — Design Spec

**Date:** 2026-06-26
**Scope:** Minimal viable integration — resolve sqlproxy published datasources
**Approach:** Build blind from API docs + sigma-migration-skills reference; backlog item for live testing

## Problem

Tableau workbooks that reference **published datasources** (hosted on Tableau
Server/Cloud) contain `<connection class="sqlproxy">` in the TWB XML. The actual
warehouse tables, columns, and calculated field definitions live on the server — not
in the file. The `ts-convert-from-tableau` skill cannot resolve these without querying
the Tableau REST API.

The CPG+Merch Promotion Performance workbook (audited 2026-06-26) is an example: both
datasources are sqlproxy published datasources. The audit showed 99.3% formula
coverage, zero untranslatable formulas — the only blocker is resolving the published
datasource columns.

## Components

Three deliverables plus a backlog item:

| # | Component | Location |
|---|---|---|
| 1 | `ts-profile-tableau` skill | `agents/cli/ts-profile-tableau/SKILL.md` |
| 2 | `ts tableau` CLI commands | `tools/ts-cli/ts_cli/commands/tableau.py` |
| 3 | Step 3.5 in ts-convert-from-tableau | `agents/cli/ts-convert-from-tableau/SKILL.md` |
| 4 | Backlog item BL-031 | `docs/backlog.md` |

---

## Component 1: `ts-profile-tableau` Skill

**Family:** `ts-profile-{platform}` (family 2)
**CoCo:** Not applicable — add to `EXPECTED_DIVERGENCES`: "Tableau Server not accessible
from Snowsight runtime"

### Profile JSON

File: `~/.claude/tableau-profiles.json` (array, matches Snowflake pattern)

```json
[
  {
    "name": "My Tableau Cloud",
    "server_url": "https://prod-apsoutheast-a.online.tableau.com",
    "site_content_url": "damiandev",
    "auth": "password",
    "username": "user@company.com",
    "password_env": "TABLEAU_PASSWORD_MY_TABLEAU_CLOUD",
    "api_version": "3.22"
  }
]
```

PAT variant:

```json
{
  "auth": "pat",
  "pat_name": "claude-migration",
  "pat_secret_env": "TABLEAU_PAT_SECRET_MY_TABLEAU_CLOUD",
  "api_version": "3.22"
}
```

### Field definitions

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Profile display name |
| `server_url` | Yes | Tableau Server/Cloud base URL (no trailing slash) |
| `site_content_url` | Yes | Path segment after `/site/` in URL; empty string for Tableau Server default site |
| `auth` | Yes | `"password"` or `"pat"` |
| `username` | If password | Tableau username (email) |
| `password_env` | If password | Env var name for password |
| `pat_name` | If pat | PAT label (not a secret) |
| `pat_secret_env` | If pat | Env var name for PAT secret |
| `api_version` | No | Default `"3.22"` |

### Credential storage

| Auth method | Keychain service | Keychain account | Env var pattern |
|---|---|---|---|
| password | `tableau-{slug}` | `{username}` | `TABLEAU_PASSWORD_{SLUG}` |
| pat | `tableau-{slug}` | `{pat_name}` | `TABLEAU_PAT_SECRET_{SLUG}` |

Slug derivation: lowercase profile name, non-alphanumeric → hyphens.
SLUG for env var: slug uppercased, hyphens → underscores.

### SKILL.md operations

1. **Add** — prompt for server URL, site content URL, auth method. Direct user to
   store credential in their own terminal (never accept in conversation). Write
   profile JSON + `~/.zshenv` export.
2. **List** — show profiles without secrets (server, site, auth method, username/PAT name)
3. **Test** — call `ts tableau signin --profile NAME`, report success/failure
4. **Remove** — delete profile entry, remove keychain entry, remove env var line

---

## Component 2: `ts tableau` CLI Commands

**Location:** `tools/ts-cli/ts_cli/commands/tableau.py`
**Registration:** `app.add_typer(tableau.app, name="tableau")` in `cli.py`

### Internal `TableauClient` class

Handles REST transport. Not exported — private to the module.

```
TableauClient(profile: dict)
  .server_url        — from profile
  .site_content_url  — from profile
  .api_version       — from profile, default "3.22"
  ._token            — session token (set by signin)
  ._site_id          — site UUID (set by signin)
  .signin()          — PAT or password sign-in
  .request(method, path, **kwargs) — authenticated request with 401 retry
  .datasources(name_filter=None)   — list/search datasources
  .datasource_fields(datasource_id) — VizQL read-metadata
```

### Sign-in

Endpoint: `POST /api/{VERSION}/auth/signin`

Request body (XML):
- Password: `<tsRequest><credentials name="EMAIL" password="PASS"><site contentUrl="SITE"/></credentials></tsRequest>`
- PAT: `<tsRequest><credentials personalAccessTokenName="NAME" personalAccessTokenSecret="SECRET"><site contentUrl="SITE"/></credentials></tsRequest>`

Response (JSON): `credentials.token` (session token), `credentials.site.id` (site UUID)

Credential loaded at sign-in time via `keyring.get_password("tableau-{slug}", account)`.

### 401 retry

On 401, refresh token once (re-signin), retry the request. Do NOT retry again — respect
Tableau's 4-strike PAT invalidation rule. For password auth, repeated retries are safer
but still capped at 1 refresh per request.

### Retryable errors

Status codes 429, 408, 502, 503, 504 retry with exponential backoff:
`delay = 1.5 * 2^(attempt-1) + random(0, 0.5)`. Max 4 attempts.

### Commands

| Command | Endpoint | Output |
|---|---|---|
| `ts tableau signin --profile NAME` | `POST .../auth/signin` | `{"site_id": "...", "api_version": "3.22"}` |
| `ts tableau datasources --profile NAME [--name FILTER]` | `GET .../sites/{SITE}/datasources[?filter=name:eq:NAME]` | JSON array of datasource objects |
| `ts tableau datasource ID --profile NAME [--fields]` | `GET .../datasources/{ID}` + optionally `POST /api/v1/vizql-data-service/read-metadata` | `{datasource: {...}, fields: [...]}` |

**Pagination:** `datasources` auto-paginates (walk `pageNumber` until
`totalAvailable` reached). Caller gets the full result set.

**Output:** JSON to stdout, diagnostics to stderr. Exit code 0 success, 1 error.

### VizQL read-metadata endpoint

`POST /api/v1/vizql-data-service/read-metadata` (note: `/api/v1/`, not versioned path)

Request:
```json
{"datasource": {"datasourceLuid": "DATASOURCE_UUID"}}
```

Response: array of field objects with `fieldName`, `fieldCaption`, `dataType`,
`columnClass` (DIMENSION/MEASURE/DERIVED), `formula` (for calculated fields).

### Testing

`tools/ts-cli/tests/test_tableau.py` — unit tests for:
- Profile loading and slug derivation
- XML sign-in request body construction (both auth methods)
- Response parsing (signin, datasources, fields)
- Retry logic (mock 429/502 → retry, 403 → fail)
- Pagination assembly

No live Tableau connection required.

---

## Component 3: Step 3.5 in `ts-convert-from-tableau`

### Trigger

Step 3 parses the TWB and detects datasources with `<connection class="sqlproxy">`.
Step 3.5 runs only if at least one sqlproxy datasource was found.

### Flow

```
1. Prompt: "Found {N} published datasource(s) on Tableau Server.
   To resolve underlying warehouse tables, I need to query the
   Tableau REST API. Do you have a Tableau profile configured?
   (Run /ts-profile-tableau to set one up)"

2. For each sqlproxy datasource:
   a. ts tableau datasources --profile NAME --name "{dbname}"
      → find datasource by display name, get its ID
   b. ts tableau datasource {ID} --profile NAME --fields
      → get field metadata (names, types, formulas)
   c. Merge resolved fields into the parsed datasource structure

3. Proceed to Step 4 with resolved column info
```

### What resolution provides

| Field | Use in migration |
|---|---|
| `fieldCaption` | Column display name → ThoughtSpot column name |
| `dataType` | real/integer/string/date/datetime/boolean → TS data type |
| `columnClass` | DIMENSION/MEASURE/DERIVED → TS column type + role |
| `formula` | Calculated field formula text → Step A3/5 formula translation |

### Graceful degradation

If user has no Tableau profile or declines:
- Log warning: "Published datasource columns will use display names from the TWB.
  Warehouse table/column mapping may need manual confirmation in Step 4."
- Proceed with TWB `<metadata-records>` column info (often has remote names,
  but no table-level warehouse info)

### SKILL.md changes

- Add Step 3.5 to the Step 0 overview step list with `[scope 1,2]` tag
- Add full Step 3.5 section between Steps 3 and 4
- Add `ts-profile-tableau` to Prerequisites (optional — only needed for sqlproxy)
- No changes to Audit mode (audit doesn't need server access — it works from the file)

---

## Component 4: Backlog Item

**BL-031 — Tableau REST API integration: live-instance testing**

- **Source:** 2026-06-26 design spec
- **Affects:** ts-profile-tableau, `ts tableau` CLI, ts-convert-from-tableau Step 3.5
- **Status:** Not started
- **Problem:** All components built from API docs + sigma reference without live
  verification. Need to confirm: PAT and password sign-in, datasource search response
  shape, VizQL read-metadata field structure, 401 retry behaviour.
- **Proposed approach:**
  1. Test against Tableau Cloud developer site
  2. Verify each CLI command independently
  3. Run end-to-end sqlproxy resolution on CPG workbook
  4. Update open-items.md with findings

---

## Repo convention checklist

| Convention | Action |
|---|---|
| Branch | `feat/tableau-api-integration` from main |
| README skills table | Add ts-profile-tableau row |
| SETUP.md | Add symlink step for ts-profile-tableau |
| CHANGELOG.md | `feat: add ts-profile-tableau skill and ts tableau CLI commands` |
| Smoke test | `tools/smoke-tests/smoke_ts-profile-tableau.py` |
| Skill naming validator | ts-profile-tableau matches family 2 pattern — no changes needed |
| Runtime coverage | Add to `EXPECTED_DIVERGENCES` in `check_runtime_coverage.py` |
| ts-cli version | Bump to 0.14.0 (MINOR — new capability) |
| ts-convert-from-tableau version | Bump MINOR (new Step 3.5) |
| Version sync | Update both `__init__.py` and `pyproject.toml` |

---

## Out of scope

- Workbook listing/download via API (YAGNI — we already have the .twb file)
- GraphQL metadata API (VizQL read-metadata is sufficient)
- View data/image fetching
- CoCo mirror of ts-profile-tableau
- Tableau Server on-premises auth (SAML, Kerberos)
