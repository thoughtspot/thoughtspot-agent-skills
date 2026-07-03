# ts-cli — Conventions

Loaded when working in tools/ts-cli/. Covers architecture, known limitations,
and the extension pattern.

## Architecture

```
ts_cli/
  cli.py              — Typer app entry point; registers command groups
  client.py           — ThoughtSpotClient REST wrapper; handles token caching and auth
  tml_lint.py         — Pre-import TML linter (pure functions, no I/O)
  model_builder.py     — Tableau TML assembly + phased-import orchestration facade (pure functions, no I/O; TWB parsing lives in ts_cli/tableau/twb.py)
  tableau_translate.py — Tableau → ThoughtSpot formula translation entry point + orchestrator facade over ts_cli/tableau/ (pure functions, no I/O)
  tableau/
    __init__.py         — package marker
    parsing.py          — formula tokenization, CSQ column maps, calc-id maps
    pre_transforms.py    — systematic pre-transforms applied before translation
    conditionals.py      — IF/IIF/CASE WHEN/ELSE translation
    functions.py         — Tableau→ThoughtSpot function + date-function mapping
    strings_types.py     — string/type conversion functions (INT, string concat, etc.)
    lod.py               — level-of-detail (LOD) expression translation
    cleanup.py           — output-cleanup transforms (post-translation)
    dag.py               — dependency DAG building, topological sort, cycle detection
    params.py            — parameter renaming, sanitisation, conflict detection
    naming.py            — name-clash detection and renaming
    validate.py           — pre-import and post-translation validation
    yaml_out.py           — TML YAML dump helpers
    twb.py                — TWB/TWBX XML parsing (tables, columns, joins, calcs, params)
    build_model.py        — pure helpers behind `ts tableau build-model` (sqlproxy scoping, merge prep, import-error parsing)
    client.py             — TableauClient (HTTP) + profile resolution; the package's one I/O module
  commands/
    auth.py       — ts auth (whoami, logout)
    profiles.py   — ts profiles list
    metadata.py   — ts metadata search
    tml.py        — ts tml export / import / lint
    connections.py — ts connections list / get / add-tables
    tables.py     — ts tables create
    tableau.py    — ts tableau (signin, datasources, download, translate-formulas, build-model)
    audit.py      — ts audit run / report
  audit/
    __init__.py       — run_audit() entry point, angle module registry
    context.py        — AuditContext dataclass + build_context()
    findings.py       — Finding dataclass + build_summary()
    checks_ai.py      — AI readiness checks (A1-A5)
    checks_data.py    — Data modeling checks (D1-D12)
    checks_human.py   — Human readiness checks (H1-H10)
    checks_perf.py    — Performance checks (P1-P18)
    checks_security.py — Security checks (S1-S10)
    report.py         — HTML report renderer (compact payload + template injection)
    report_template.html — Self-contained HTML template with CSS/JS
    erd.py            — ERD data generation for audit reports (parses Model+Table TML)
    test_fixtures.py  — Realistic test data generator
```

Each command group is a separate module in `commands/`. `cli.py` imports and registers each.

## Version sync

`ts_cli/__init__.py __version__` must always match `pyproject.toml version`. Bump both together.
Current version: **0.27.0**. Run `python tools/validate/check_version_sync.py` to verify.

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

## Adding an audit check

1. Write the `check_XX` function in the appropriate `audit/checks_*.py` module
   (AI → `checks_ai.py`, Data → `checks_data.py`, etc.). The function receives
   an `AuditContext` and returns a list of `Finding` objects.
2. Add the function to `ALL_CHECKS` in the same module — this is the registry
   that `run_audit()` iterates.
3. Add unit tests in `tools/ts-cli/tests/` covering the check's logic.
4. Add a row to `agents/cli/ts-audit/references/check-catalog.md` with the check ID,
   what it detects, and severity logic.
5. Bump version in both `__init__.py` and `pyproject.toml`.
6. Run `pytest tools/ts-cli/tests/` and `python tools/validate/check_version_sync.py`.
