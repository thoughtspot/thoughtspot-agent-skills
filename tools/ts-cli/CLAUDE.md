# ts-cli — Conventions

Loaded when working in tools/ts-cli/. Covers architecture, known limitations,
and the extension pattern.

## Architecture

```
ts_cli/
  cli.py              — Typer app entry point; registers command groups
  client.py           — ThoughtSpotClient REST wrapper; handles token caching and auth
  tml_lint.py         — Pre-import TML linter (pure functions, no I/O)
  tml_common.py       — platform-neutral TML YAML serialization (dump_tml_yaml) + import-response GUID parsing (extract_imported_guid) — relocated from tableau/ (BL-063 PR5); pure functions, Genie-vendorable
  formula_common.py   — platform-neutral formula/name transforms (resolve_name_collisions, add_formula_prefix, expr_is_aggregated, fix_double_aggregation) — relocated from model_builder.py/tableau/naming.py (BL-063 PR5); pure functions, Genie-vendorable
  model_builder.py     — Tableau TML assembly + phased-import orchestration facade (pure functions, no I/O; TWB parsing lives in ts_cli/tableau/twb.py)
  tableau_translate.py — Tableau → ThoughtSpot formula translation entry point + orchestrator facade over ts_cli/tableau/ (pure functions, no I/O)
  snowflake_ops.py     — Semantic View diff (normalise_expr/exprs_differ/compute_change_set) + DDL lint (lint_sv_ddl) behind `ts snowflake` (pure functions, no I/O)
  spotql_ops.py        — Aggregate-function classification (AGGREGATE_FUNCS/is_aggregate_expr/classify_expr/classify_model_columns) behind `ts spotql classify-columns` (pure functions, no I/O)
  aggregate/
    __init__.py          — package marker
    signatures.py         — Answer/Liveboard TML -> normalized query signatures (grouping columns, filters, date bucket) behind `ts aggregate signatures` (pure functions, no I/O)
    measures.py           — measure decomposition rewrite plans (SUM/MIN/MAX/COUNT/AVG/ratio classification) for aggregate models (pure functions, no I/O)
    lattice.py            — grain lattice: bucket/coverage rule + candidate generation from signatures + rewrite plans behind `ts aggregate recommend` (pure functions, no I/O)
    scoring.py            — cost-based (profiled) / coverage-based (unprofiled) greedy candidate selection with a marginal-gain curve behind `ts aggregate recommend` (pure functions, no I/O)
    sqlgen.py             — aggregate SELECT / profiling SQL / DDL emission across snowflake/databricks/bigquery dialects behind `ts aggregate profile`/`generate` (pure functions, no I/O); fallback path only as of Task 18 — see spotql_aggregate.py
    spotql_aggregate.py   — Task 18/19: build a SpotQL SELECT for a candidate's grain (build_spotql — measures by display name, raw date columns, no bucket fn; single-component SUM/MIN/MAX/COUNT measures only, AVG/RATIO raise UnsupportedMeasureError) and wrap ThoughtSpot-compiled warehouse SQL as aggregate DDL (wrap_as_ddl — outer DATE_TRUNC+reagg aggregating SELECT when a date descriptor carries a bucket, plain positional pass-through otherwise), reusing sqlgen.build_ddl/_date_trunc for materialization shapes and per-dialect date truncation — the default DDL SELECT source behind `ts aggregate profile`/`generate`, because ThoughtSpot's own SQL generation resolves joins correctly on role-playing/ambiguous-path dimensions where sqlgen.build_select's hand-rolled walker can be wrong (pure functions, no I/O)
    generate.py           — aggregate Table/Model TML assembly + `aggregated_models` association patch on the primary Model, reusing tables.py/model_builder.py rather than hand-assembling TML (pure functions, no I/O)
    history.py            — match Snowflake QUERY_HISTORY GROUP BY shapes to signatures, producing reweighted signature weights behind `ts aggregate history` (pure functions, no I/O)
  dependency/
    __init__.py          — re-exports mutate.py + backup.py public entry points
    mutate.py             — REMOVE/REPOINT TML dict transforms (apply_remove/apply_repoint dispatchers + remove_columns_from_*/repoint_* helpers) behind `ts dependency mutate` (pure functions, no I/O; BL-083)
    backup.py             — backup filename/delete-order/v2-type-map/restore-policy/rollback-order/manifest helpers behind `ts dependency backup`/`rollback` (pure functions, no I/O; BL-083)
    apply.py              — drift/obj_id/import-outcome-matrix/verify-body/9c-ordering/set-delete-guard/chart-role decision helpers behind `ts dependency apply-change` (pure functions, no I/O; BL-083 PR2)
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
    naming.py            — name-clash detection (detect_name_clashes/apply_name_clash_renames) for Tableau-side collisions; resolve_name_collisions relocated to ts_cli/formula_common.py (BL-063 PR5), re-exported here for backward compat
    reconcile.py           — column cleanup + schema reconciliation for build-model (suffix strip, qualify, suggest/apply name maps)
    validate.py           — pre-import and post-translation validation
    yaml_out.py           — shim — dump_tml_yaml relocated to ts_cli/tml_common.py (BL-063 PR5); re-exported here for backward compat
    twb.py                — TWB/TWBX XML parsing (tables, columns, joins, calcs, params)
    classify.py            — formula tier classification behind `ts tableau classify-formulas` (classify_formulas/TRANSLATABLE_TIERS/UNTRANSLATABLE_TIERS; delegates the translatable verdict to tableau_translate.py so audit and migrate agree)
    build_model.py        — pure helpers behind `ts tableau build-model` (sqlproxy scoping, merge prep, import-error parsing)
    client.py             — TableauClient (HTTP) + profile resolution; the package's one I/O module
  databricks/
    __init__.py         — package marker (stdlib + PyYAML only — Genie-vendorable, no HTTP/auth deps)
    mv_parse.py         — Metric View YAML -> structured dict behind `ts databricks parse-mv`: source classification, joins walk, top-level assembly; re-exports the mv_expr/mv_window API (pure functions, no I/O; BL-063 PR2)
    mv_expr.py          — dimension/measure SQL expression classification (pure functions, no I/O)
    mv_window.py        — window-spec parsing: 5 range values, offset, BL-098 density flag (pure functions, no I/O)
    mv_sql.py           — Databricks SQL expression -> ThoughtSpot formula text (tokenizer, function map, NULLIF/COALESCE collapsing) behind `ts databricks translate-formulas`; re-exports the CASE/CAST/NOT/IS/IN/BETWEEN handlers from mv_sql_constructs.py so translate_sql_expr/UntranslatableError/tokenize stay the public API (pure functions, no I/O; BL-063 PR3)
    mv_sql_constructs.py — CASE/CAST/NOT/IS/IN/BETWEEN keyword-construct handlers split out of mv_sql.py under the file-size warn line; late-imports mv_sql's expression primitives to avoid a circular import (pure functions, no I/O; BL-063 PR3)
    mv_translate.py     — parsed Metric View -> translated ThoughtSpot formulas behind `ts databricks translate-formulas`: dot-path resolution, LOD windows, conditional aggregates, cross-measure inlining via dependency DAG; re-exports translate_window_measure from mv_window_translate.py (pure functions, no I/O; BL-063 PR3)
    mv_window_translate.py — windowed-measure translation (trailing/leading/cumulative/current decision tree, BL-098 sparse-data-risk annotations) split out of mv_translate.py under the file-size warn line; late-imports mv_translate's make_resolver/_formula_measure to avoid a circular import (pure functions, no I/O; BL-063 PR3)
  commands/
    auth.py       — ts auth (whoami, logout)
    profiles.py   — ts profiles list
    metadata.py   — ts metadata search
    tml.py        — ts tml export / import / lint
    connections.py — ts connections list / get / add-tables
    tables.py     — ts tables create
    tableau.py    — ts tableau (signin, datasources, download, parse, classify-formulas, translate-formulas, build-model)
    snowflake.py  — ts snowflake (diff, lint-ddl)
    spotql.py     — ts spotql (generate-sql, fetch-data, classify-columns)
    dependency.py — ts dependency (mutate, backup, rollback) — BL-083
    dependency_apply.py — ts dependency apply-change (Step 9 destructive orchestrator; attaches to dependency.app) — BL-083 PR2
    audit.py      — ts audit run / report
    databricks.py — ts databricks (parse-mv, translate-formulas, build-model) — BL-063 PR2/PR3/PR4
    aggregate.py  — ts aggregate (signatures, recommend, profile, history, generate) — aggregate-model advisor engine
    aggregate_rls.py — RLS command-layer wiring for `ts aggregate` (Task 23): _attach_rls_conflicts (recommend advisory surfacing) + _propagate_rls_or_fail_closed (generate security gate — fails closed on incomplete tables-dir or grain missing an RLS filter column) over the pure aggregate/rls.py engine; split out of aggregate.py to stay under the file-size gate, imported lazily from recommend/generate
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
Current version: **0.49.0**. Run `python tools/validate/check_version_sync.py` to verify.

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
