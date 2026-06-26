# ts-cli — Conventions

Loaded when working in tools/ts-cli/. Covers architecture, known limitations,
and the extension pattern.

## Architecture

```
ts_cli/
  cli.py          — Typer app entry point; registers command groups
  client.py       — ThoughtSpotClient REST wrapper; handles token caching and auth
  commands/
    auth.py       — ts auth (whoami, logout)
    profiles.py   — ts profiles list
    metadata.py   — ts metadata search
    tml.py        — ts tml export / import
    connections.py — ts connections list / get / add-tables
    tables.py     — ts tables create
```

Each command group is a separate module in `commands/`. `cli.py` imports and registers each.

## Version sync

`ts_cli/__init__.py __version__` must always match `pyproject.toml version`. Bump both together.
Current version: **0.14.0**. Run `python tools/validate/check_version_sync.py` to verify.

## Required dependencies

`PyYAML>=6.0` is a required runtime dependency — `tables.py` uses `yaml.dump` to generate
table TML. Do not remove it from `pyproject.toml`.

## connection_name not connection_fqn

The CLI always uses the string display name for connections — never a GUID.
`connection_name` in table specs maps to the `name:` field inside the `connection:` block
in table TML. Passing a GUID where a name is expected will silently produce invalid TML.

## Token cache location

Tokens are cached per-profile in `/tmp/ts_token_<slug>.txt` (permissions 0600) and managed
by `client.py`. Do not change this path without updating the auth documentation in
`agents/cli/ts-profile-thoughtspot/SKILL.md` (Technical Reference section).

## Connection fetch (v2)

`connections get` and `connections add-tables` fetch connection state via the v2
endpoint `POST /api/rest/2.0/connection/search` (helper `_fetch_connection_v2`), adapted
to the legacy `dataWarehouseInfo.databases` shape via `_adapt_v2_databases`. This replaced
the v1 `/tspublic/v1/connection/fetchConnection` endpoint, which was removed on newer
ThoughtSpot Cloud builds (404). The warehouse hierarchy is only populated for
`SERVICE_ACCOUNT` connections; OAuth/PKCE connections return an empty hierarchy (callers
tolerate this — `add-tables` proceeds with new tables only). No remaining v1 endpoints are
used anywhere in the repo.

## Adding a command

1. Add a module to `commands/` (or add a subcommand to an existing module)
2. Register the command group in `cli.py`
3. Add a reference entry to `README.md`
4. Update any `SKILL.md` that uses the command
5. Add unit tests in `tools/ts-cli/tests/`
6. Bump version in both `__init__.py` and `pyproject.toml`
