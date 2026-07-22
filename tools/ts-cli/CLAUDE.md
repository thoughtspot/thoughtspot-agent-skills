# ts-cli — Conventions

Loaded when working in tools/ts-cli/. Covers architecture, known limitations,
and the extension pattern.

## Architecture

```
ts_cli/
  cli.py              — Typer app entry point; registers command groups
  client.py           — ThoughtSpotClient REST wrapper; handles token caching and auth
  tml_lint.py         — Pre-import TML linter: lint_tml (single-document I1/I2/I4/I5/I8 + guid-placement invariants) (pure functions, no I/O)
  tml_common.py       — platform-neutral TML YAML serialization (dump_tml_yaml) + import-response GUID parsing (extract_imported_guid) — relocated from tableau/ (BL-063 PR5); pure functions, Genie-vendorable
  formula_common.py   — platform-neutral formula/name transforms (resolve_name_collisions, add_formula_prefix, expr_is_aggregated, fix_double_aggregation) — relocated from model_builder.py/tableau/naming.py (BL-063 PR5); pure functions, Genie-vendorable
  model_builder.py     — Tableau TML assembly + phased-import orchestration facade (pure functions, no I/O; TWB parsing lives in ts_cli/tableau/twb.py)
  tableau_translate.py — Tableau → ThoughtSpot formula translation entry point + orchestrator facade over ts_cli/tableau/ (pure functions, no I/O)
  snowflake_ops.py     — Semantic View diff (normalise_expr/exprs_differ/compute_change_set) + DDL lint (lint_sv_ddl) + SQL var substitution (parse_var_assignment/substitute_sql_vars, behind `ts snowflake exec` — BL-079) behind `ts snowflake` (pure functions, no I/O)
  sv_parse.py          — Semantic View DDL → structured dict (parse_sv_ddl) behind `ts snowflake parse-sv` — tables/relationships/dimensions/metrics/facts/custom_instructions/verified_queries/extension extraction (BL-100; pure functions, no I/O; reuses snowflake_ops clause-extraction helpers)
  sv_sql.py            — Snowflake SQL expression → ThoughtSpot formula text (translate_sql_expr); tokenizer + recursive descent + Snowflake function map (ts-snowflake-formula-translation.md as data) behind `ts snowflake translate-formulas` (BL-100; pure functions, no I/O)
  sv_translate.py      — Parsed SV → translated ThoughtSpot formulas (translate_sv_formulas); identifier resolution, column classification, window/LOD/semi-additive/USING handling behind `ts snowflake translate-formulas` (BL-100; pure functions, no I/O)
  sv_build_model.py    — Snowflake SV → ThoughtSpot Model TML assembly (build_model_tml_sv); inline Scenario B joins (equi/range/ASOF), SV synonym→display name, private columns, fact table detection, strip_formulas for two-pass import; imports formula_common shared transforms (BL-100 PR3; pure functions, no I/O)
  sv_introspect.py     — INFORMATION_SCHEMA → tables-spec + tables map (map_snowflake_type, build_tables_spec, build_tables_map, detect_column_gaps); Snowflake type → ThoughtSpot type mapping, cross-schema query building, column gap detection against existing TS tables (BL-100 PR4; pure functions, no I/O)
  sv_build_sv.py       — ThoughtSpot Model TML → Snowflake Semantic View DDL (build_sv_ddl); column_id resolution, column classification (dimension/metric/time_dimension), to_snake aliasing, relationship naming with collision avoidance, metric topological ordering, CA extension JSON, synonym/comment handling (BL-100 PR5; pure functions, no I/O)
  spotql_ops.py        — Aggregate-function classification (AGGREGATE_FUNCS/is_aggregate_expr/classify_expr/outermost_func/classify_model_columns; incl. semi-additive last_value/first_value → SUM wrapper) behind `ts spotql classify-columns` (pure functions, no I/O)
  promote.py           — Formula promotion merge (extract_answer_formulas/detect_duplicates/map_references/build_merged_model) behind `ts model promote-formula` (pure functions, no I/O; BL-066)
  aggregate/
    __init__.py          — package marker
    signatures.py         — Answer/Liveboard TML -> normalized query signatures (grouping columns, filters, date bucket) behind `ts aggregate signatures` (pure functions, no I/O)
    measures.py           — measure decomposition rewrite plans (SUM/MIN/MAX/COUNT/AVG/ratio classification) for aggregate models (pure functions, no I/O)
    lattice.py            — grain lattice: bucket/coverage rule + candidate generation from signatures + rewrite plans behind `ts aggregate recommend` (pure functions, no I/O)
    scoring.py            — cost-based (profiled) / coverage-based (unprofiled) greedy candidate selection with a marginal-gain curve behind `ts aggregate recommend` (pure functions, no I/O)
    sqlgen.py             — aggregate SELECT / profiling SQL / DDL emission across snowflake/databricks/bigquery dialects behind `ts aggregate profile`/`generate` (pure functions, no I/O); fallback path only as of Task 18 — see spotql_aggregate.py
    spotql_aggregate.py   — Task 18/19: build a SpotQL SELECT for a candidate's grain (build_spotql — measures by display name, raw date columns, no bucket fn; single-component SUM/MIN/MAX/COUNT measures only, AVG/RATIO raise UnsupportedMeasureError) and wrap ThoughtSpot-compiled warehouse SQL as aggregate DDL (wrap_as_ddl — outer DATE_TRUNC+reagg aggregating SELECT when a date descriptor carries a bucket, plain positional pass-through otherwise), reusing sqlgen.build_ddl/_date_trunc for materialization shapes and per-dialect date truncation — the default DDL SELECT source behind `ts aggregate profile`/`generate`, because ThoughtSpot's own SQL generation resolves joins correctly on role-playing/ambiguous-path dimensions where sqlgen.build_select's hand-rolled walker can be wrong (pure functions, no I/O)
    generate.py           — aggregate Table/Model TML assembly + `aggregated_models` association patch on the primary Model, reusing tables.py/model_builder.py rather than hand-assembling TML (pure functions, no I/O)
    rls.py                — RLS extraction + grain-conflict detection + rule propagation onto the aggregate table (extract_rls/rls_filter_columns/candidate_rls_conflict/add_rls_columns_to_candidate/propagate_rls; tuple-keyed, identical-rule dedup) — wired by commands/aggregate.py + aggregate_rls.py (pure functions, no I/O)
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
    verify.py              — source↔output migration-fidelity gate behind `ts tableau verify` (verify_conversion: structural/formula_equivalence/validity/limitation_coverage checks, diffing a `ts tableau parse` output against the generated Model TML; reuses classify.py's tier split — so an untranslatable formula's absence from model.formulas is never flagged as a drop — and tml_lint.py's lint_tml for validity, never re-implementing invariant logic. Model↔table-TML dangling-reference checking is a separate concern, covered by `ts tml lint --dir`) (pure functions, no I/O)
    build_model.py        — pure helpers behind `ts tableau build-model` (sqlproxy scoping, merge prep, import-error parsing)
    dashboards.py         — pure dashboard/visual extraction (open item #20): `<dashboard>` zones → build_from_spec visuals (mark + fields by shelf/role/measure + calc-id→caption resolution + date buckets + grid tiles). Emitted by `ts tableau parse` (`dashboards` key); consumed by `ts tableau build-liveboard --input <parse.json> --model-name ...` so parse→liveboard runs with no hand-assembled spec
    liveboard.py          — pure Answer + tabbed-Liveboard emission behind `ts tableau build-liveboard` (role-aware axis layout, chart-needs floor, overrides replay); ThoughtSpot-side logic ported from the standalone Power BI converter's generate_tml.py (_answer_tml/_answer_tml_explicit/_liveboard_tml). Live-verified fixes (v0.55.0): bucketed dates use the resolved output name (`Month(Date)`) not the raw name; a hand-authored (display-name) `custom_chart_config` is DROPPED (its refs must be GUIDs — fresh import else errors `Invalid GUID string`), keeping only genuine captured GUID-based configs
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
    mv_emit_expr.py     — TS-formula tokenizer + recursive-descent parser -> dict-AST (reverse direction) behind `ts databricks build-mv`; re-exports UntranslatableError from formula_common.py (pure functions, no I/O; Genie-vendorable)
    mv_emit_sql.py      — dict-AST -> Databricks-SQL string (reverse direction): AGG_MAP/SCALAR_FN_MAP/COND_AGG/PASSTHROUGH_FN dicts, operator-precedence-aware emit_sql, plus the raw-measure aggregation wrapper (is_aggregate_present/wrap_measure_if_needed, Task 18 Finding 1) that matches ThoughtSpot's own SUM-at-query-time semantics for a no-aggregate formula measure (pure functions, no I/O; Genie-vendorable)
    mv_emit_base.py     — Foundation helpers for the reverse direction: physical-column indexing (build_column_index), column resolvers (make_col_resolver), and formula-AST [ref] resolution (resolve_refs), plus to_snake; split out of mv_emit.py so mv_emit_joins.py/mv_emit_classify.py can both depend on it without a cycle back through mv_emit.py (pure functions, no I/O; Genie-vendorable)
    mv_emit_joins.py    — join assembly (reverse direction): build_joins walks model_tables[].joins[] breadth-first from the fact table emitting nested Metric View join nodes + dot-paths; split out of mv_emit.py under the file-size gate; imports Foundation from mv_emit_base.py, never from mv_emit.py (pure functions, no I/O; Genie-vendorable)
    mv_emit_classify.py — column classification (classify_column) + non-window dimension/measure/filter emitters + LOD dimension-window emission (emit_lod_dimension), split out of mv_emit.py under the file-size gate; imports Foundation from mv_emit_base.py, never from mv_emit.py; does not depend on mv_emit_joins.py (pure functions, no I/O; Genie-vendorable)
    mv_emit.py          — ThoughtSpot Model TML -> Databricks Metric View YAML orchestrator (reverse direction) behind `ts databricks build-mv`: fact-table detection, cross-reference role resolution, the two emission passes, dangling-ref cascade, build_metric_view top-level entry point; re-exports Foundation (mv_emit_base.py), join assembly (mv_emit_joins.py), classification/LOD emitters (mv_emit_classify.py), and the window-measure API (mv_emit_window.py) so existing callers/tests keep importing from mv_emit unchanged (pure functions, no I/O)
    mv_emit_window.py   — window-measure emission (moving/cumulative/semi-additive/period-offset), split out of mv_emit.py under the file-size gate; mirrors the mv_translate.py/mv_window_translate.py split for the reverse direction (pure functions, no I/O; Genie-vendorable)
    mv_build_view.py    — Metric View YAML doc -> `CREATE VIEW ... WITH METRICS LANGUAGE YAML AS $$...$$` DDL + build_summary (the `ts databricks build-mv` stdout JSON contract) + default_view_name; the one place an MV YAML body is dumped via `yaml.safe_dump` directly, with a fail-loud guard against a literal `$$` inside the body (pure + PyYAML only, no HTTP/auth/typer deps; Genie-vendorable)
  qlik/
    __init__.py         — package marker
    ir.py               — normalized Qlik-app IR dataclasses (QlikApp/Table/Column/MasterMeasure/Sheet/Chart) — the extract↔transform contract (pure, JSON-serializable)
    parsing.py          — offline .qvf inventory extraction (SQLite-embedded path + byte-scan fallback) behind `ts qlik parse --mode offline` (pure functions, no I/O; degrades to warnings on an opaque .qvf, never crashes)
    engine.py           — engine-artifacts inventory extraction (Qlik Engine export dir) behind `ts qlik parse --mode engine-artifacts` (pure functions, no I/O)
    live_engine.py      — LIVE Qlik Engine JSON-RPC-over-websocket extraction behind `ts qlik parse --mode engine` (one of the package's two I/O modules, mirrors tableau/client.py); `websocket` imported lazily in QlikEngine.__init__ so the package imports without the `[qlik]` extra — missing extra raises a clear `pip install 'thoughtspot-cli[qlik]'` RuntimeError
    cloud.py            — LIVE Qlik Cloud (SaaS) extraction behind `ts qlik parse --mode qlik-cloud`: REST (/api/v1 items + data-connections) + Engine (QIX via live_engine); the package's other I/O module. Api key from --api-key/QLIK_API_KEY only, never printed/written. `requests` is a base dep; websocket comes via live_engine + the `[qlik]` extra
    functions.py        — Qlik expression → ThoughtSpot formula translation + the 199-row qlik_ts_formula_map (data/); flags Set Analysis `$`-selection and no-equivalent functions NEEDS REVIEW rather than downgrading (pure functions, no I/O)
    build_model.py      — Table + Model TML assembly + mapping.json behind `ts qlik build-model`; reuses model_builder + formula_common (add_formula_prefix id-refs) + tml_common.dump_tml_yaml (pure functions, no I/O)
    answers.py          — Answer + tabbed-Liveboard emission behind `ts qlik build-liveboard` (one tab per Qlik sheet; each chart → embedded Answer) (pure functions, no I/O)
    data/               — qlik_ts_formula_map.{json,csv} (packaged via package-data)
  commands/
    auth.py       — ts auth (whoami, logout)
    profiles.py   — ts profiles list
    metadata.py   — ts metadata search
    model.py      — ts model (promote-formula) — BL-066
    tml.py        — ts tml export / import / lint
    connections.py — ts connections list / get / add-tables
    tables.py     — ts tables create
    tableau.py    — ts tableau (signin, datasources, download, parse, classify-formulas, translate-formulas, build-model, build-liveboard, verify)
    qlik.py       — ts qlik (parse, build-model, build-liveboard) — Qlik Sense → ThoughtSpot converter (I/O only; logic in ts_cli/qlik/). `--mode` selects the extractor: offline / engine-artifacts (positional <source>) or the live qlik-cloud (--tenant/--app-id/--api-key) / engine (--engine/--app-id/--header) paths; live modes need the `[qlik]` extra
    snowflake.py  — ts snowflake (diff, lint-ddl, exec, parse-sv, translate-formulas, build-model, introspect, build-sv)
    spotql.py     — ts spotql (generate-sql, fetch-data, classify-columns)
    spotter.py    — ts spotter (answer) — natural-language → Spotter answer via ai/answer/create; the "Spotter last-mile" for the conversion skills (pure normalise_answer_response + thin I/O)
    dependency.py — ts dependency (mutate, backup, rollback) — BL-083
    dependency_apply.py — ts dependency apply-change (Step 9 destructive orchestrator; attaches to dependency.app) — BL-083 PR2
    audit.py      — ts audit run / report
    databricks.py — ts databricks (parse-mv, translate-formulas, build-model, build-mv) — BL-063 PR2/PR3/PR4; build-mv is the reverse (TS Model -> Databricks Metric View) deterministic emitter over mv_emit.py/mv_build_view.py, emit-only (no --profile, no ThoughtSpot/Databricks connection)
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
Current version: **0.75.0**. Run `python tools/validate/check_version_sync.py` to verify.

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
