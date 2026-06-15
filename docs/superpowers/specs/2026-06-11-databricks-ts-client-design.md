# Databricks Runtime: ThoughtSpot Client + Conversion Skills — Design Spec

**Date:** 2026-06-11 (recreated 2026-06-15 from backlog BL-005 + session memory)
**Status:** Approved — ready for implementation planning
**Backlog:** BL-005

---

## Problem

The repo's Databricks skills (`ts-convert-to-databricks-mv`, `ts-convert-from-databricks-mv`)
run only from CLI (Claude Code / Cortex Code CLI). Databricks users working inside the
platform (notebooks, Genie Code) cannot use them because the `ts` CLI requires shell access
and OS keychain — neither available in Databricks.

Beyond conversion skills, platform-agnostic skills (`ts-object-model-coach`,
`ts-object-answer-promote`, `ts-dependency-manager`) could also run from Databricks if a
client layer existed.

**Reference implementation validated the pattern:**
`github.com/aalladin/databricks-metrics-view-2-thoughtspot-tml-pipeline`

---

## Solution

Build `agents/databricks/` as a third runtime alongside CLI and CoCo:

| Component | Purpose |
|---|---|
| `ts_client.py` | Single-file ThoughtSpotClient with full ts-cli parity |
| `ts_profile_setup.py` | Interactive setup wizard via `dbutils.widgets` |
| `token_refresh.py` | Scheduled job for token rotation (12h) |
| 2 Genie Code skills | `ts-convert-to-databricks-mv` + `ts-convert-from-databricks-mv` |
| Shared reference files | Deployed to workspace alongside notebooks |
| `SETUP.md` | End-to-end deployment guide |
| Unit tests | pytest-based, mocked `dbutils.secrets` and `requests` |

---

## Architecture

```
agents/databricks/
  notebooks/
    ts_client.py              ← consumed via %run by skills and other notebooks
    ts_profile_setup.py       ← interactive setup wizard
    token_refresh.py          ← scheduled Databricks Job
  skills/
    ts-convert-to-databricks-mv/SKILL.md
    ts-convert-from-databricks-mv/SKILL.md
  SETUP.md
  tests/
    test_ts_client.py
    test_profile_setup.py
    conftest.py               ← mocked dbutils fixture
```

Skills and notebooks consume `agents/shared/` reference files deployed to the
Databricks workspace alongside the notebooks.

---

## Component 1: `ts_client.py` — ThoughtSpotClient

### Design principles

- **Single file** — consumed via `%run ./ts_client` in notebooks; no package install needed.
- **Full ts-cli parity** — every `ts` CLI command has a corresponding method.
- **Databricks Secrets for credentials** — one scope per ThoughtSpot profile.
- **In-memory token caching** — no filesystem; tokens live in the notebook session.
- **No dependency on `ts` CLI, `keyring`, or OS keychain.**

### Class interface

```python
class ThoughtSpotClient:
    """ThoughtSpot REST API client for Databricks notebooks."""

    def __init__(self, profile: str = "default"):
        """Load profile from Databricks Secrets scope 'thoughtspot-{profile}'.
        
        Reads: base_url, auth_method, username, and the credential
        (token, password, or secret_key) from the scope.
        """

    # ── Auth ──────────────────────────────────────────────────────────
    def whoami(self) -> dict:
        """GET /api/rest/2.0/auth/session/user"""

    def get_token(self) -> str:
        """Return cached bearer token, refreshing if expired."""

    def logout(self) -> None:
        """Clear cached token."""

    # ── Metadata ──────────────────────────────────────────────────────
    def metadata_search(self, *, type: str = "LOGICAL_TABLE",
                        subtypes: list[str] | None = None,
                        name: str | None = None,
                        guid: str | None = None,
                        tags: list[str] | None = None,
                        include_hidden: bool = False,
                        fetch_all: bool = False) -> list[dict]:
        """POST /api/rest/2.0/metadata/search — auto-paginates when fetch_all=True."""

    def metadata_get(self, guid: str, *, type: str = "LOGICAL_TABLE") -> dict:
        """Get a single metadata object by GUID."""

    def metadata_dependents(self, guids: list[str], *,
                            type: str = "LOGICAL_TABLE") -> list[dict]:
        """POST /api/rest/2.0/metadata/search with dependent_object_version=V2."""

    def metadata_delete(self, guids: list[str], *, type: str = "LOGICAL_TABLE") -> dict:
        """POST /api/rest/2.0/metadata/delete"""

    def metadata_report(self, sources: list[str], *, fast: bool = False,
                        depth: int = 3) -> dict:
        """Full dependency report — walks dependents, probes TML."""

    # ── TML ───────────────────────────────────────────────────────────
    def tml_export(self, guids: list[str], *, fqn: bool = False,
                   associated: bool = False, format: str = "YAML",
                   parse: bool = False, type: str | None = None,
                   include_obj_id: bool = False,
                   include_obj_id_ref: bool = False,
                   include_guid: bool = True) -> list[dict]:
        """POST /api/rest/2.0/metadata/tml/export"""

    def tml_import(self, tmls: list[str], *, policy: str = "PARTIAL",
                   create_new: bool = True) -> dict:
        """POST /api/rest/2.0/metadata/tml/import"""

    # ── Connections ───────────────────────────────────────────────────
    def connections_list(self, *, type: str = "SNOWFLAKE") -> list[dict]:
        """POST /api/rest/2.0/connection/search — auto-paginates."""

    def connections_get(self, connection_id: str) -> dict:
        """POST /tspublic/v1/connection/fetchConnection"""

    def connections_add_tables(self, connection_id: str,
                               tables: list[dict]) -> dict:
        """Fetch-merge-update: adds tables without removing existing ones."""

    # ── Tables ────────────────────────────────────────────────────────
    def tables_create(self, tables: list[dict], *,
                      retries: int = 3, retry_delay: float = 5.0) -> dict:
        """Generate Table TML from specs, import, resolve GUIDs."""

    # ── Users ─────────────────────────────────────────────────────────
    def users_search(self, *, name: str | None = None,
                     group: str | None = None) -> list[dict]:
        """POST /api/rest/2.0/users/search"""

    # ── Orgs ──────────────────────────────────────────────────────────
    def orgs_search(self) -> list[dict]:
        """POST /api/rest/2.0/orgs/search"""

    def orgs_switch(self, org_id: int) -> dict:
        """PUT /api/rest/2.0/orgs/{org_id}/switch"""

    # ── Variables ─────────────────────────────────────────────────────
    def variables_search(self, *, name: str | None = None) -> list[dict]:
        """POST /api/rest/2.0/vw/search"""

    def variables_update(self, variable_id: str, values: list[dict]) -> dict:
        """PUT /api/rest/2.0/vw/{id}/values"""
```

### Auth flow

```
┌─────────────────────┐
│  __init__(profile)  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│  Read from Databricks Secrets scope         │
│  'thoughtspot-{profile}':                   │
│    base_url, auth_method, username,         │
│    token | password | secret_key            │
└────────┬────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────┐
│  auth_method?                │
├──────┬───────────┬───────────┤
│token │ password  │secret_key │
└──┬───┘     └──┬──┘     └──┬─┘
   │            │            │
   ▼            ▼            ▼
Use directly  POST /auth    POST /auth
              /token        /token
              (basic auth)  (secret key)
   │            │            │
   └────────────┼────────────┘
                ▼
        ┌──────────────┐
        │ Cache token   │
        │ in memory     │
        │ (self._token) │
        └──────────────┘
```

Three auth methods supported:

| Method | Secrets stored | Token exchange |
|---|---|---|
| `bearer_token` | `base_url`, `auth_method`, `username`, `token` | None — token used directly |
| `password` | `base_url`, `auth_method`, `username`, `password` | `POST /api/rest/2.0/auth/token/full` with `username` + `password` |
| `secret_key` | `base_url`, `auth_method`, `username`, `secret_key` | `POST /api/rest/2.0/auth/token/full` with `username` + `secret_key` |

Token caching is in-memory only (`self._token`, `self._token_expiry`). No filesystem
writes. Token refresh happens automatically when a request gets a 401 or when the
cached token is past its TTL (default: 30 min for exchanged tokens, no expiry tracking
for bearer tokens).

### Credential storage — Databricks Secrets

One scope per ThoughtSpot profile:

```
Scope: thoughtspot-{profile}
  Keys: base_url, auth_method, username, token|password|secret_key
```

Created by `ts_profile_setup.py`. Skills reference profiles by name:

```python
client = ThoughtSpotClient("my-staging")
```

### Error handling

All API calls raise `ThoughtSpotAPIError` on non-2xx responses:

```python
class ThoughtSpotAPIError(Exception):
    def __init__(self, status_code: int, message: str, endpoint: str):
        self.status_code = status_code
        self.endpoint = endpoint
        super().__init__(f"[{status_code}] {endpoint}: {message}")
```

The `configuration` field is scrubbed from error bodies before raising (per
`.claude/rules/security.md` — never expose connection credentials in errors).

---

## Component 2: `ts_profile_setup.py` — Setup Wizard

Interactive notebook using `dbutils.widgets` for input:

### Workflow

1. **Collect inputs** via widgets:
   - Profile name (text, default: "default")
   - ThoughtSpot base URL (text)
   - Auth method (dropdown: bearer_token / password / secret_key)
   - Username (text)
   - Credential value (text — entered via widget, immediately stored to Secrets)

2. **Create Databricks Secrets scope** `thoughtspot-{profile}` if it doesn't exist.

3. **Store each key** via `dbutils.secrets.put(scope, key, value)`.

4. **Test connection** — instantiate `ThoughtSpotClient(profile)` and call `whoami()`.

5. **Report success** — display user details, org, privileges.

### Security constraints

- Credential values are read from widgets and written directly to Secrets.
  They are never assigned to variables that persist in notebook output.
- Widget values are cleared after setup completes.
- The notebook output cell shows only the test result (user display name,
  org, privilege count) — never the credential itself.

---

## Component 3: `token_refresh.py` — Scheduled Token Rotation

Lightweight script for a Databricks Job (recommended: every 12 hours).
Only needed for `password` and `secret_key` auth methods — `bearer_token`
profiles manage their own token lifecycle externally.

### Workflow

1. List all Secrets scopes matching `thoughtspot-*`.
2. For each scope where `auth_method` is `password` or `secret_key`:
   - Read credentials from Secrets.
   - Exchange for a fresh token via the auth endpoint.
   - Store the new token back to the scope's `token` key.
3. Log success/failure per profile (no credential values in logs).

### Why not just refresh on demand?

Genie Code agent sessions may be short-lived. Pre-refreshing tokens ensures
the first API call in a session doesn't hit an expired token and trigger a
visible delay. The 12h interval matches ThoughtSpot's default token TTL
with margin.

---

## Component 4: Two Genie Code Conversion Skills

Adapted from `agents/cli/ts-convert-to-databricks-mv/SKILL.md` and
`agents/cli/ts-convert-from-databricks-mv/SKILL.md` for the Genie Code
Agent runtime.

### Key differences from CLI versions

| Aspect | CLI | Genie Code |
|---|---|---|
| API calls | `ts` CLI commands | `ThoughtSpotClient` methods via `%run` |
| Auth | OS keychain + `--profile` flag | Databricks Secrets + profile name |
| File I/O | Local filesystem | Databricks workspace files or notebook variables |
| Interactive prompts | Claude Code conversation | Genie Code agent conversation |
| Shared references | Symlinked from repo | Deployed to workspace |

### Skill structure

Each skill's SKILL.md references the client notebook:

```python
# At the top of any skill notebook or code cell
%run ./ts_client
client = ThoughtSpotClient("my-profile")
```

The conversion logic (parsing MV YAML, generating TML, mapping formulas)
is identical to the CLI version — only the I/O layer changes.

---

## Component 5: Shared Reference Files

The following files from `agents/shared/` are deployed to the Databricks
workspace alongside notebooks:

```
workspace/
  thoughtspot-skills/
    notebooks/
      ts_client.py
      ts_profile_setup.py
      token_refresh.py
    skills/
      ts-convert-to-databricks-mv/SKILL.md
      ts-convert-from-databricks-mv/SKILL.md
    shared/
      mappings/ts-databricks/
        ts-databricks-formula-translation.md
        ts-from-databricks-rules.md
        ts-databricks-properties.md
      schemas/
        thoughtspot-table-tml.md
        thoughtspot-model-tml.md
        thoughtspot-formula-patterns.md
      worked-examples/databricks/
        ts-from-databricks.md
        ts-to-databricks.md
```

Deployment is via Databricks Asset Bundle (`databricks bundle deploy`) —
see Component 6.

---

## Component 6: Deployment — Databricks Asset Bundle

Deployment uses a **Databricks Asset Bundle** (`databricks bundle deploy`).
A `databricks.yml` at `agents/databricks/` defines what gets deployed and where.

### Why Asset Bundle

- One-command deploy: `databricks bundle deploy -t <target>`
- Declarative: workspace paths, jobs, and permissions defined in YAML
- Repeatable: same bundle deploys identically across workspaces
- Can create the token refresh job automatically (no manual job setup)
- Standard Databricks pattern — no custom tooling

### `databricks.yml` structure

```yaml
bundle:
  name: thoughtspot-skills

workspace:
  root_path: /Workspace/thoughtspot-skills

artifacts:
  notebooks:
    type: notebook
    path: notebooks/
  skills:
    type: file
    path: skills/
  shared:
    type: file
    source: ../../shared/          # agents/shared/ — same files CLI and CoCo use
    path: shared/

resources:
  jobs:
    token_refresh:
      name: "ThoughtSpot Token Refresh"
      schedule:
        quartz_cron_expression: "0 0 */12 * * ?"   # every 12 hours
        timezone_id: UTC
      tasks:
        - task_key: refresh
          notebook_task:
            notebook_path: notebooks/token_refresh

targets:
  dev:
    workspace:
      host: https://your-workspace.cloud.databricks.com
  prod:
    workspace:
      host: https://your-workspace.cloud.databricks.com
```

### Deployment workflow

```bash
# One-time: install the Databricks CLI
pip install databricks-cli

# Deploy everything — notebooks, skills, shared files, token refresh job
cd agents/databricks
databricks bundle deploy -t dev

# After deploy: open ts_profile_setup.py in Databricks, run it interactively
```

### SETUP.md

The deployment guide covers:

1. **Prerequisites** — Databricks workspace, Unity Catalog, Databricks CLI, ThoughtSpot instance
2. **Configure target** — edit `databricks.yml` targets with workspace host
3. **Deploy** — `databricks bundle deploy -t <target>`
4. **Create profile** — run `ts_profile_setup.py` interactively in Databricks
5. **Test connection** — verify `whoami()` output
6. **Verify token refresh job** — check the job was created and trigger a test run
7. **Genie Code usage** — how to invoke skills from Genie Code Agent mode

---

## Component 7: Unit Tests

pytest-based, no live Databricks or ThoughtSpot connection required.

### Mocking strategy

```python
# conftest.py
@pytest.fixture
def mock_dbutils():
    """Mock dbutils.secrets with in-memory dict."""
    secrets = {}
    class MockSecrets:
        def get(self, scope, key): return secrets.get(f"{scope}/{key}", "")
        def put(self, scope, key, value): secrets[f"{scope}/{key}"] = value
        def list(self, scope): return [k.split("/")[1] for k in secrets if k.startswith(f"{scope}/")]
    class MockDbutils:
        secrets = MockSecrets()
    return MockDbutils(), secrets
```

### Test matrix

| Area | Tests |
|---|---|
| Auth — bearer token | Init reads token from secrets, `whoami()` sends correct header |
| Auth — password exchange | Init exchanges password for token, caches result |
| Auth — secret_key exchange | Init exchanges secret_key for token, caches result |
| Auth — token refresh | Expired token triggers re-exchange on next API call |
| Auth — 401 retry | 401 response triggers one token refresh + retry |
| metadata_search | Correct request body, pagination, subtype filtering |
| metadata_search — fetch_all | Multiple pages fetched and concatenated |
| metadata_dependents | Correct payload, flat normalization of v2 response |
| metadata_delete | Correct payload shape, GUID list |
| metadata_report | Walks dependents, probes TML, builds report |
| tml_export | Default flags, `--fqn`, `--associated`, `--parse` equivalents |
| tml_export — parse | YAML edoc parsed into structured dict |
| tml_import | Correct payload, policy flag, create_new flag |
| connections_list | Auto-pagination, type filter |
| connections_get | v1 endpoint, correct request shape |
| connections_add_tables | Fetch-merge-update workflow, columns preserved |
| tables_create | TML generation, import, GUID resolution, retry on JDBC error |
| users_search | Name and group filters |
| orgs_search / orgs_switch | Correct endpoints |
| variables_search / variables_update | Correct endpoints and payloads |
| Error handling | Non-2xx → ThoughtSpotAPIError, configuration scrubbed |
| Profile setup | Scope creation, secret storage, test connection |

---

## ts-cli → ThoughtSpotClient command mapping

| ts CLI command | ThoughtSpotClient method | Notes |
|---|---|---|
| `ts auth whoami` | `whoami()` | |
| `ts auth token` | `get_token()` | |
| `ts auth logout` | `logout()` | |
| `ts metadata search` | `metadata_search()` | All flags mapped to kwargs |
| `ts metadata get` | `metadata_get()` | |
| `ts metadata dependents` | `metadata_dependents()` | Flat normalization included |
| `ts metadata report` | `metadata_report()` | Full ReportEngine port |
| `ts metadata delete` | `metadata_delete()` | |
| `ts tml export` | `tml_export()` | All flags including `--parse` |
| `ts tml import` | `tml_import()` | stdin → `tmls` list parameter |
| `ts connections list` | `connections_list()` | |
| `ts connections get` | `connections_get()` | v1 endpoint |
| `ts connections add-tables` | `connections_add_tables()` | Fetch-merge-update |
| `ts tables create` | `tables_create()` | Retry + GUID resolution |
| `ts profiles list` | (via Secrets scope listing) | No direct equivalent needed |
| `ts users search` | `users_search()` | |
| `ts orgs search` | `orgs_search()` | |
| `ts orgs switch` | `orgs_switch()` | |
| `ts variables search` | `variables_search()` | |
| `ts variables update` | `variables_update()` | |

---

## Phases

| Phase | Deliverable | Depends on |
|---|---|---|
| **Phase 1** (this spec) | `ts_client.py` + setup/refresh notebooks + Asset Bundle + 2 conversion skills + shared files + tests + SETUP.md | — |
| **Phase 2** | Genie Code skills for 4 platform-agnostic skills (model-coach, answer-promote, dependency-manager, profile-thoughtspot) | Phase 1 |

---

## Files created

| File | Purpose |
|---|---|
| `agents/databricks/notebooks/ts_client.py` | ThoughtSpotClient class |
| `agents/databricks/notebooks/ts_profile_setup.py` | Interactive setup wizard |
| `agents/databricks/notebooks/token_refresh.py` | Scheduled token rotation |
| `agents/databricks/skills/ts-convert-to-databricks-mv/SKILL.md` | Genie Code skill |
| `agents/databricks/skills/ts-convert-from-databricks-mv/SKILL.md` | Genie Code skill |
| `agents/databricks/databricks.yml` | Asset Bundle definition |
| `agents/databricks/SETUP.md` | Deployment guide |
| `agents/databricks/tests/test_ts_client.py` | Unit tests |
| `agents/databricks/tests/test_profile_setup.py` | Setup wizard tests |
| `agents/databricks/tests/conftest.py` | Mock dbutils fixture |

## Files NOT modified

- `tools/ts-cli/` — the CLI is unchanged; the notebook client is a parallel implementation
- `agents/cli/` — CLI skills unchanged
- `agents/coco-snowsight/` — CoCo skills unchanged
- `agents/shared/` — shared files consumed as-is, deployed to workspace by SETUP.md

---

## What this design does NOT cover

- **Phase 2 skills** — model-coach, answer-promote, dependency-manager, profile-thoughtspot
  adapted for Genie Code. These are follow-on work after Phase 1 proves the client layer.
- **Connection creation** — BL-011 (`ts-object-connection-create`) is a separate initiative.
  The client will add a `connections_create()` method when that ships.
- **Non-Databricks notebook runtimes** — Jupyter, Colab, etc. The client is Databricks-specific
  (Secrets, `dbutils`, `%run`). A generic notebook client would need a different auth layer.
