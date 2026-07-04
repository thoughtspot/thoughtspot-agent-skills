# Changelog

All notable changes to this repo are documented here.
Skill-level changes are tracked in each skill's own `## Changelog` section.

---

## 2026-07-04
- fix: bump ts-cli to v0.32.1 — classify-formulas classifies per datasource (was flattening multi-datasource workbooks and deduping shared calc names; live-test finding)
- chore: bump ts-cli to v0.32.0
- feat: ts tableau parse + classify-formulas commands (Tableau audit/migrate convergence)

## 2026-07-03
- chore: bump ts-cli to v0.31.0 (ts spotql classify-columns — BL-087)
- chore: bump ts-cli to v0.30.0 (ts snowflake diff + lint-ddl — BL-063 quick wins)
- chore: bump ts-cli to v0.29.0 (ts tableau build-model --table-name-map)
- docs: full repo audit 2026-07-03 — report + same-day routing (PRs #168-#176, BL-073..BL-087), agentic→deterministic codification review
- feat: add 5 audit-harvest validators — `check_no_inline_requests` (SKILL.md code fences must not instruct `requests`/`urllib` calls, finding 5.2), a `DEPRECATED_V2_ENDPOINTS` denylist in `check_no_v1_endpoints` (bare batch `/template/variables/update-values` path, finding 13.1), `check_pagination_convention` (AST-scoped guard against a hard-capped `record_size` literal with no pagination loop, finding 14.2), `check_slash_command_refs` (every `/ts-<skill>` mention in agents/ docs must resolve to a real skill directory, finding 1.1), and `check_skill_flag_usage` (cross-checks every `ts <group> <command> --<flag>` a SKILL.md documents against the real typer command tree, finding 11.1b). Wired into pre-commit + CI; dated the two `check_smoke_tests` ALLOWLIST exemptions with BL-076 (finding 6.3)
- chore: bump ts-cli to v0.28.0 — per-identifier variables endpoint, full auto-pagination, dependent matched-columns field, dev extra
- chore: bump ts-cli to v0.28.1 — Tableau fail-loud: 13 spatial + USERATTRIBUTE user functions
- fix: ts-cli v0.27.0 — impact-report deep probes (RLS/Monitor/Joins/Spotter AI surface/Column alias rows) no longer report `checked=True, found=0` when the backing TML export raises; a failed probe now flips the affected row(s) to `checked=False` and surfaces a warning in the report (audit 4.1). `ThoughtSpotClient.request()` now clears the cached token and retries once on a 401 instead of treating a rotated/revoked token as valid for up to 23h (audit 4.2). `ts tml import`/`ts tml lint` gain `--file` (repeatable) and `--dir` (non-recursive) raw-TML-file input, alongside the existing stdin JSON-array interface — makes the `ts tml import --file <path>` command already documented in ts-convert-from-snowflake-sv/ts-convert-from-databricks-mv SKILL.md actually work (audit 11.1)
- fix: ts-audit v2.4.0 — 3 report bugs: scorecard GUID-matching, false orphans from pagination + associated export
- chore: bump ts-cli to v0.26.6
- chore: bump ts-cli to v0.26.5 — ACOS/ASIN/ATAN/COT rejected loudly at translate time (BL-072 partial)
- chore: bump ts-cli to v0.26.4 — move TableauClient to ts_cli/tableau/client.py; check_file_size allowlist now empty
- fix: ts-cli v0.26.3 — ts-load-source-data synthetic data: a numeric column (INTEGER/FLOAT) whose name merely contains "name"/"customer" no longer gets random person-name strings (type mismatch); it now falls through to the numeric generator. Adds a regression test
- chore: bump ts-cli to v0.26.2 — BL-069 follow-ups: dead-code removal, filter_unresolvable_formulas annotation fix, module-health baseline re-key
- chore: bump ts-cli to v0.26.1 — decompose build_model_cmd into ts_cli/tableau/build_model.py + flow functions (BL-069 follow-up)
- feat: update ts-object-model-erd to v1.7.0 — subject-area grouping: a **Group by** selector colors tables into subject areas via three selectable strategies (Name prefix; Graph cluster via deterministic Louvain-style modularity — ~20 communities on the 79-table GTM export; Fact neighbourhood via nearest-fact `(dist,factId)` relaxation). Non-destructive shared display — accent stripe per node, dark AA-contrast tint on overview/LOD blocks, and a legend with ghost-only single-group highlight; layout, fact/dim fill, and RLS/focus borders untouched. Also hardens `esc()` to escape quotes (+ fixes an unescaped `findingCard` data-target) and refreshes the Review-notes panel after Clear notes
- feat: update ts-object-model-erd to v1.6.0 — notes UX: save/delete give immediate feedback (shared `commitNotes()` exit, inspector re-renders after save/delete so Delete is reachable without a reload, self-dismissing "Saved ✓"/"Note deleted" confirmation); new **Notes** filter chip highlights every noted table (including at overview/LOD zoom) and keeps a noted join emphasized even without a noted endpoint, correctly enabling/disabling on model load (including Share-HTML baked notes) and never leaving the diagram ghosted after the last note is removed; new **Review notes** panel lists every note with a Table/Join/"not in model" tag (stale keys are delete-only, never clickable), click-to-jump moves the canvas, inline delete
- feat: ts-cli v0.26.0 — 14 Tableau function translations implemented (were silent pass-throughs); unmapped functions and unknown date units now fail loud at translate time; scalar MAX/MIN and IN(...) scan bugs fixed
- docs: ts-convert-from-tableau doc/mapping drift refresh — SKILL.md command fixes, mapping-file alignment with v0.26.0 code, matrix/open-items verification pass, gap documentation + 2 new backlog items

## 2026-07-02
- refactor: split Tableau pipeline into ts_cli/tableau/ package (BL-069); bump ts-cli to v0.25.4
- fix: validator test fixtures no longer corrupt the real repo when pytest runs under pre-commit hook env (GIT_* scrub)
- feat: update ts-object-model-erd to v1.5.0 — overview legibility (semantic zoom): node/edge strokes (incl. the edge hit-path) now use `vector-effect:non-scaling-stroke` so borders stay crisp at any zoom; below 0.5× zoom, tables render as bold color-coded overview blocks (solid saturated kind fill + state-aware border + centered title) instead of full column cards, restoring full detail above the threshold; no layout/position change
- feat: update ts-object-model-erd to v1.4.0 — large-model navigation: scroll/trackpad pans (pinch/⌘-scroll zooms), pan-drag no longer resets focus, arrow/`+`/`-`/`0` keyboard nav, an always-on collapsible minimap with click/drag-to-navigate, a shared `MIN_K=0.12` fit floor (fit/wheel/zoom-out), fit-to-focus, and search-zooms-to-readable. Also fixes a latent crash when a join references a table with no Table TML and no `model_tables` entry
- fix: update ts-object-model-erd to v1.3.0 — `build_erd.py` ingests a `ts tml export` JSON dump directly (routes model/table by TML content, not filename) and fails loud when no model is present, instead of silently rendering an empty diagram; SKILL.md Step 3→5 rewritten as a clean pipe. RLS model corrected: highlight only the table a rule is defined on (secured) and any table its expression references (in RLS path) — removed the incorrect join-propagation ("RLS inherited via joins", "RLS edge", propagating rule cards, join-ancestor subgraph). Column inspector: column groups are now flat headed sections instead of nested `<details>`, which left column rows hidden in some browsers
- feat: update ts-object-model-erd to v1.2.0 — `--ai-analysis` flag injects an agent-synthesized business-context corpus (domain/objectives/audience/questions/AI-instructions) into the ERD; column inspector surfaces per-column AI context + synonyms; RLS legend parity (secured tables show red border + lock by default); double-click/compare focus hides out-of-scope tables; parser handles the nested `rls_rules` TML shape
- feat: add `check_module_health` validator — a cyclomatic-complexity ratchet (radon) that blocks new/worsening god-functions against a committed baseline; wired into pre-commit (staged) and CI (full). Adds an automated component to repo-audit Angle 4 (Tools quality)
- docs: repo-audit rubric now names the code-health sweep tooling — `vulture` (dead code, Angle 1), `jscpd` (code duplication, Angle 11), and `agentlinter` as an optional local-only instruction-hygiene advisory (Angle 2); these run during the sweep, not as per-PR gates
- chore: remove dead code — `agents/cli/ts-audit/analyzer.py` + `report.py` and their orphaned tests (4,722 lines), superseded by the codified engine in `tools/ts-cli/ts_cli/audit/*` (the audit skill runs via `ts audit`, not these files; one test already imported a since-deleted module). BL-069 raised to high priority; BL-070 marked partially done
- chore: remove dead import (`render_json`) in ts-cli metadata command (vulture)
- fix: audit cluster heatmap no longer rolls unattributable findings onto the first model in multi-model audits (was inflating that model's severity across angles)
- fix: ERD fact/dimension classifier — an outgoing join alone no longer marks a table a fact; only real (visible) measures do, with measureless pass-through tables as bridges
- fix: ERD viewer no longer errors when clicking a flagged fan-out join with no attached finding
- chore: bump ts-cli to v0.25.3
- refactor: ERD generation consolidated to a single definition in `agents/shared/erd` (parser + assembler moved out of the ts-object-model-erd skill); ts-audit ERD embed now consumes it instead of a duplicate parser
- fix: ERD dimension/fact classifier — hidden and non-measure formula columns (e.g. RLS/parameter helper formulas) no longer promote a dimension to a fact
- feat: ERD layered layout clusters joined tables via Sugiyama median crossing-reduction
- chore: bump ts-cli to v0.25.2
- feat: ERD — AI domain summary, multi-select filter chips, RLS red colour scheme, grouped controls bar, join-tree double-click
- chore: bump ts-cli to v0.25.1

## 2026-07-01
- feat: wire ts-object-model-erd into ts-audit report — ERD button opens interactive diagram per model
- feat: ts-cli performance — `requests.Session` pooling, BFS frontier batching, Liveboard export batching
- fix: bump `requests>=2.32.4` (CVE-2024-35195, CVE-2023-32681), raise Python floor to >=3.10
- docs: update Muze charting status to phase 1 GA, Snowflake Advanced constructs YAML coverage
- chore: bump ts-cli to v0.25.0
- feat: add ts-object-model-erd skill
- feat: add shared ERD renderer module (`agents/shared/erd/`) — data-driven CSS + JS + render.py ported from validated mockup
- feat: update ts-audit to v2.2.0 — report UI fixes (accessible heatmap, clickable breadcrumbs/KPIs, check metadata, AI analysis panel)
- chore: bump ts-cli to v0.24.0
- feat: add `ts audit report` command — unified HTML report
- chore: bump ts-cli to v0.23.0
- chore: delete superseded `efficiency_report.py`
- feat: add `ts audit run` command — codifies all 51 audit checks (A1-A5, D1-D12, H1-H10, P1-P18, S1-S10) as deterministic Python
- fix(audit): include report_template.html in wheel package-data

## 2026-06-28
- feat: add Migration Pace (Fast/Complete) to ts-convert-from-tableau — Fast parks failed formulas; Complete enters bounded fix cycle; Step 12.5 resume prompt for post-report fixes
- feat: add `--max-retries` flag and enriched `formulas_dropped_on_import` dict to `build-model` command
- feat: wire `ts tableau build-model` into SKILL.md Step 7 Phase 2 — replaces inline Python formula assembly (root cause of 1,389-tool-call migration)
- feat: add dual-join table alias detection to model_builder — same physical table with different aliases (e.g. `d_partner` / `d_partner1`) now preserved
- feat: add `validate_pre_import()` + `add_formula_prefix()` integration to `build-model` command (both flows)
- feat: add `fix_bare_refs()` post-pass — table-qualifies bare `[Column]` refs and prefixes formula cross-refs in `build-model --existing-guid` flow
- feat: add single-table force-remap for sqlproxy columns — 100% remap when model has one table
- feat: add `max(bool)=false` pattern detection to `validate_pre_import()`
- fix: strip Tableau double-quote wrapping from parameter defaults and member values
- fix: orphaned END/CASE keyword strip after failed `convert_if_then`/`convert_case_when` parsing
- fix: extend `_DATE_INDICATORS` regex to catch date column names (prevents `else ''` on date expressions)
- fix: `--max-retries` default 10→25 for complex workbooks with cascading formula dependencies
- docs: update SKILL.md — auth via `ts profiles list`, model TML schema read, GUID capture, duplicate detection, datasource name matching
- chore: bump ts-cli to v0.21.0
- chore: add `check_skill_cli_usage.py` regression validator — prevents drift back to inline Python TML assembly

## 2026-06-27
- feat: add `ts tableau build-model` command (ts-cli 0.18.0) — deterministic TWB-to-model-TML pipeline: parses TWB XML, resolves all internal refs (Calculation_ and copy-style), translates formulas, resolves name collisions, applies formula_ prefix, fixes double aggregation, splits into phased import files by dependency level. New `model_builder.py` module with pure functions for all 8 model-level transforms
- chore: bump ts-cli to v0.18.0
- feat: update `ts-convert-from-tableau` — add scope 4 (Models only) and scope 5 (Tables only) migration modes with per-step scope annotations
- chore: bump ts-cli to v0.17.0 — 9 new pre-transforms (ifnull stripping, sum_if conversion, date arithmetic, scalar MAX/MIN, comment stripping, CSQ alias resolution, no-keyword LOD, if/then/else validation, operator spacing); 156 new tests
- feat: update `ts-convert-from-tableau` — orphan calc detection (Step 3g), Phase 1.5 base model checkpoint, excluded formulas + review flags report sections (BL-053), blend risk classification (BL-045), formula complexity + realistic coverage estimate (BL-047), targeted retry with context cache (BL-049), compound connection prompt (BL-051)
- feat: add `ts-load-source-data` skill v1.0.0 — load CSV data into Snowflake (or generate synthetic data from schema definitions) for ThoughtSpot to connect to; adds `ts-load-*` naming family to skill-naming.md and check_skill_naming.py
- feat: add `ts tableau translate-formulas` CLI command (ts-cli 0.16.0) — deterministic 14-step Tableau → ThoughtSpot formula translation pipeline with dependency DAG, cross-reference resolution, column scoping, parameter conflict detection. Pure-function engine in `tableau_translate.py`
- chore: bump ts-cli to v0.16.0
- feat: update `ts-convert-from-tableau` — add Step 3.6 (join confirmation for published datasources), CLI formula translation reference in Step 5b, two-phase model import in Step 7 (base model first, then formulas with iterative error recovery), cross-reference depth reporting in audit mode (Step A3/A4)

## 2026-06-26
- feat: add `ts load` CLI command group — schema inference, synthetic data generation, Snowflake loading
- feat: add `ts tableau download` command (ts-cli 0.15.0) — download published datasource content (TDSX) from Tableau Server/Cloud, extract archive, validate CSV files for row integrity (column count consistency, corrupt lines with proper quoted-field handling). Prerequisite for BL-010 (`ts-load-source-data`)
- chore: bump ts-cli to v0.15.0
- chore: bump ts-cli to v0.14.0 — register `ts tableau` command group (signin, datasources, datasource); add `--tableau` flag to `ts profiles list`
- feat: add `ts-profile-tableau` skill v1.0.0 — Tableau Server/Cloud credential setup (password + PAT auth), profile management (add/list/test/remove), stored in `~/.claude/tableau-profiles.json`
- feat: add `ts tableau` CLI commands (ts-cli 0.14.0) — `signin` (PAT + password auth), `datasources` (list/search with auto-pagination), `datasource` (detail + `--fields` for VizQL read-metadata). TableauClient with 401 retry and retryable-error backoff
- feat: add Step 3.5 to `ts-convert-from-tableau` — auto-resolve published datasources (sqlproxy) via Tableau REST API; graceful degradation when no Tableau profile configured

## 2026-06-25
- feat: update `ts-object-model-spotql-query` to v1.2.0 — add `references/architecture.md`, the "Why SpotQL" value-prop & architecture reference vs raw DB SQL: ThoughtSpot never executes SpotQL (compiles it to deterministic warehouse SQL via the same QueryGen as Liveboards/Answers/Search/Spotter; the LLM's SQL is intent, never run); semantic-layer guarantees (RLS/CLS, model filters, join defs, governed metrics/LOD/semi-additive, custom calendars, multi-fact chasm/fan-trap resolution); architecture advantages (determinism/traceability, cross-product consistency, physical-layer abstraction + dialect portability, single point of change, governed scale); the hybrid Token-based-Answers (primary) + SpotQL (expressibility fallback) flow with a verification layer unified across both transformers (co-existence + parity). Mermaid diagram + ASCII fallback. SKILL.md capability bullet + References row; README skills table deep-links it as the "Why SpotQL" starting point.
- feat: update `ts-object-model-spotql-query` to v1.1.0 — add `references/integration.md` (raw SpotQL API for non-CLI consumers); Step 6 emits paste-ready request bodies; Step 2 TML parsing hardened (`properties.column_type`, `formulas[]` via `formula_id`, deterministic raw-vs-aggregate-formula classification); capability summary added; Step 1 accepts Model GUID/URL with search as fallback. Record `connection_type` / callosum endpoint finding in open-items.md.
- feat: add `ts-object-model-spotql-query` skill v1.0.0 — query a ThoughtSpot Model with SpotQL: write Semantic SQL (grounded in bundled rules/UDF/pattern references lifted from agent-expressibility-eval), validate it to warehouse SQL via `ts spotql generate-sql`, execute via `fetch-data`, and review the results. The single-question primitive; accuracy / regression / feature / known-limitation testing are documented as compositions over it. Verified live on champ-staging.
- chore: bump ts-cli to v0.13.0 — add `ts spotql generate-sql` / `ts spotql fetch-data` (run SpotQL Semantic SQL against a Model; JSON output, structured query errors); add `raise_for_status` opt-out to the HTTP client so callers can surface 4xx query-error bodies
- refactor: rename `ts-dependency-audit` → `ts-audit` — the skill is a read-only health assessment, not a dependency-graph operation; add new `ts-audit` naming family (#8) to `skill-naming.md` and `check_skill_naming.py`

## 2026-06-18
- feat: add `ts-audit` skill v1.0.0 (originally `ts-dependency-audit`) — cluster-wide ThoughtSpot environment audit across five angles (42 checks): AI Readiness (description/synonym coverage, Spotter readiness score), Data Modeling (complexity, joins, duplicates, grain, overlap classification, zero-column tables), Human Readiness (names, hidden columns, orphans, formula promotion, stale objects), Performance (SQL Views, scalar formulas, progressive joins/filters, date constraints, column sprawl), Security (PII detection, indexing without RLS, CLS gaps, credentials). Interactive HTML report with cluster heatmap, per-model scorecards, and by-check drill-down. Usage analysis (BI Server) planned for Phase 2.

## 2026-06-17
- feat: ts-cli 0.11.0 → 0.12.0 — add `ts connections create` (Snowflake **key-pair** auth, no tables): `POST /api/rest/2.0/connection/create` with `authenticationType=KEY_PAIR`, the private key read from `--private-key-path` into the `private_key` config attribute (never logged), `validate=false`. The three `ts-convert-from-*` skills now offer **creating a new connection** at the connection step instead of only selecting an existing one (snowflake-sv full create path; tableau create path when the source is Snowflake; databricks-mv gets the explicit "stop & instruct" fallback — native PAT/OAuth create backlogged as BL-036).
- feat: codify the pre-import TML gate (audit angle 11). `ts tml lint` now also checks **I8** (duplicate `column_id` — a hard import rejection); the three `ts-convert-from-*` skills replace their copy-pasted hand-written grep gate with a `ts tml lint` call (snowflake-sv 1.11.2, databricks-mv 1.5.2, tableau 1.14.2). New `check_no_inline_tml_gate.py` guards the migration (fails if a CLI convert skill re-adds a hand-rolled `grep … aggregation:` gate), wired into pre-commit + CI — mirroring `check_no_v1_endpoints`. ts-cli 0.10.1 → 0.11.0.
- feat: first full audit sweep via the `repo-audit` runner (44 findings: 5 high) + remediations. Quick-win fixes: currency-anchor validator extended to `agents/shared/schemas/` (presence now CI-gated, staleness stays a soft nudge) with anchors added to all 16 schema files; fixed 8 broken slash-command references (`/ts-profile-setup`→`/ts-profile-thoughtspot`, `/snowflake-profile-setup`→`/ts-profile-snowflake`); corrected ts-cli README `--create-new` default (was documented backwards) + `--policy` values; corrected provably-wrong product-currency claims in `snowflake-schema.md` (`facts[]`/`sample_values`/filter-labels now YAML-expressible) and `databricks-metric-view.md` (Metric Views GA 2026-04-02, Preview-channel obsolete; v0.1 legacy). Converter emit changes deferred to BL-031/BL-032 pending live verification. Filed BL-030…BL-035. Reports: `docs/audit/2026-06-17-{external,full}.md` (inaugural manual ledger preserved as `-inaugural-full.md`).
- feat: establish a repeatable repo-audit framework (`.claude/rules/repo-audit.md`). Codifies the two-bucket rule (every finding → a validator or a dated backlog item), an internal/external angle taxonomy (the 12 internal angles are per-PR validators; external angles **13 product-currency**, **14 performance**, **16 dependency-currency** run on a weekly specialist sweep; **15 fidelity** parked). Adds `check_audit_freshness.py` (soft nudge when an external sweep or full audit is due by time **or** by accumulated work — never auto-runs), `check_mapping_currency.py` (per-PR soft nudge on stale platform-mapping *currency anchors*), currency anchors on all 10 `agents/shared/mappings/` files, and the inaugural audit ledger `docs/audit/2026-06-17-full.md`. Both nudges wired into `pre-commit.sh`. Includes the on-demand `repo-audit` Workflow runner (`.claude/workflows/repo-audit.js`, `scope: external | full`) — per-platform specialist + performance + dependency finders → synthesis → a report saved under `docs/audit/`. Execution is nudge-driven and on-demand, **no scheduled cron**. Designed config-driven for reuse in other repos.
- feat: harden three validators (final repo-audit Low items). Add `check_no_v1_endpoints.py` — an AST-based guard that fails CI/pre-commit if any non-test, non-docstring Python literal calls a `/tspublic/v1/` endpoint (wired into both `scripts/pre-commit.sh` and `validate.yml`); docstring mentions and test assertions are exempt. Tighten `check_secrets.py` placeholder detection so short markers (`test`/`my`/`xxx`/`fake`) only match as whole `\W`-delimited tokens, not arbitrary substrings (a secret merely *containing* those letters is no longer waved through). Make `check_coverage_matrix.py` reject dateless `BACKLOG` exemptions — each must now carry a target date or `#NNN`/`BL-NNN` ref; added BL-029 for the three skills still owing a coverage matrix.
- feat: ts-cli v0.10.0 — add `ts tml lint`, a connection-free pre-import linter for the model invariants `VALIDATE_ONLY` accepts silently (guid placement, I1 unpaired formula, I2 aggregation-in-formula, I4 model_table id≠name, I5 COUNT_DISTINCT on a physical column); exits 1 on findings so it composes with `&&`. Also adds central HTTP-error handling in `client.request()` — non-2xx now prints one secret-free diagnostic line (preferring the TS error body's `debug`/`error`/`message`) and exits 1 instead of dumping a traceback. (Codification Phase 1 from the repo quality audit.)
- fix(databricks): correct the Genie SETUP.md shared-path — shared refs live under `.assistant/skills/shared/` (matching `deploy.sh` and the skills' `../shared/` references), not `.assistant/shared/` (the documented manual install was broken). Add a `databricks` column to `generate_parity.py`/`PARITY.md` so the Genie runtime is visible in the matrix, and document `agents/databricks/` as a deliberately-separate runtime in `runtime-coverage.md`. (From the repo quality audit.)
- fix: ts-convert-from-tableau v1.14.1 — string **parameters** must be `CHAR` not `VARCHAR` (ThoughtSpot rejects VARCHAR list params); add a MEASURE-vs-ATTRIBUTE classification rule (formula is a measure if it transitively references a measure formula; numeric physical columns default to MEASURE; qualify bare unbracketed column refs). From the live Catalog Health Workbook migration.
- docs: add BL-027 (explicit table→ThoughtSpot binding instead of search-and-guess) and BL-028 (Audit mode for the visualization layer) to the backlog — both from the Catalog Health migration.
- docs: add `agents/shared/schemas/thoughtspot-chart-types.md` — verified `answer.chart.type` enum (44 values) + analytical-intent → chart-type mapping + full **Muze charting library (`ADVANCED_*`)** spec (custom_chart_config shelf model, early-access, verified live on se-thoughtspot); cited by ts-convert-from-tableau
- feat: ts-convert-from-tableau v1.14.0 — add a Legacy-vs-Muze charting-library prompt (Step 10-charts); on Muze, emit `ADVANCED_*` + `custom_chart_config` (Tableau Color → slice-with-color, small multiples → trellis-by) for cartesian/pivot intents with Legacy fallback for the rest
- docs: add BL-026 + design `docs/designs/ts-object-liveboard-builder.md` (build-the-best-liveboard skill)

## 2026-06-16
- chore: migrate the last v1 API (`/tspublic/v1/connection/fetchConnection`, removed/404 on newer builds) to v2 `connection/search`; ts-cli v0.9.0 (`_fetch_connection_v2`/`_adapt_v2_databases`) + databricks `ts_client.py`; no v1 endpoints remain in the repo
- feat: ts-convert-from-tableau v1.11.0 — reorder so the source-table question (exist/create/search) comes before any connection selection or search; add connection-scoped vs instance-wide search (`--name` pattern, `metadata_header.dataSourceName` filter)
- feat: add the same connection-scoped vs instance-wide table search to ts-convert-from-snowflake-sv (v1.10.0) and ts-convert-from-databricks-mv (v1.4.0)
- feat: add a how-to-identify-the-connection prompt (name it / filter by partial string / list all) to the connection-selection step of all three CLI from-* conversion skills — ts-convert-from-tableau (v1.12.0), ts-convert-from-snowflake-sv (v1.11.0), ts-convert-from-databricks-mv (v1.5.0)
- feat: ts-convert-from-tableau v1.13.0 — add a migration-scope choice (Models+Liveboards / Tables+Models only / Liveboards-only with an existing-model picker: GUID/name/filter/list-all, models found via `--subtype WORKSHEET` + `worksheetVersion == "V2"`); fix the model `obj_id` reuse bug (a fresh model's requested obj_id is reassigned by ThoughtSpot — read the real one back before referencing it in liveboard viz/cohort bindings); add an efficiency section (batch independent prompts, single-pass parse, one model export for obj_id + param UUIDs + resolved names)

## 2026-06-14
- feat: BL-024 — row-offset table calcs (INDEX/LOOKUP/FIRST/LAST/SIZE) translate via native TS window functions (`moving_sum`, `first_value`, `last_value`, `rank`) instead of SQL pass-through (which fails for DATE/numeric ORDER BY columns); ts-convert-from-tableau v1.10.0; live-verified 2026-06-15
- chore: retire Cursor runtime — delete `agents/cursor/` (14 .mdc rules, SETUP.md, install scripts), remove all Cursor references from validators, pre-commit hook, rules, README, backlog, and auditor; closes BL-017
- docs: add data-blend-to-model shared reference — two-datasource Tableau blend → single ThoughtSpot model with LEFT_OUTER join worked example

## 2026-06-13
- docs(BL-018): map four previously-unmapped SV features to ThoughtSpot — range joins (GAP-08), filter labels (GAP-10), view-backed sources (GAP-04), verified queries → NLS Feedback TML (GAP-05); update `ts-from-snowflake-rules.md` DDL format + mapping sections, `sv-to-ts-gap-analysis.md`, `thoughtspot-model-tml.md` (remove `is_mandatory`, correct `apply_on_tables` semantics), and `backlog.md` (BL-019/BL-020 for Databricks/Tableau parity)
- feat(from-snowflake-sv): v1.9.0 — identifier resolution engine: facts parsing (BL-003b), metric→fact resolution (BL-003c), double aggregation via group_aggregate (BL-003), window metrics referencing metrics (GAP-13), joinless SV handling (GAP-03/BL-004)
- fix(from-snowflake-sv): fact references use `[formula_<id>]` syntax, not display name — live-verified; add `if()` parenthesization fix; add identifier resolution worked example
- docs: add `ts-from-snowflake-identifier-resolution.md` worked example — facts, metric-on-fact, double aggregation, verified end-to-end
- fix(coco): mirror parity — port PT1 pass-through policy and error-010256 rule to CoCo skills; reverse-port name-normalisation rule to CLI; fix count_distinct example (audit C8/F2/F11)
- fix(snowflake-sv): Phase 1 audit — fail-loud SV DDL parsing (C5), LEFT_OUTER join default (F5), authority fix (F4), discovery SQL fix (F8), Mode C comparison fix (F7), INFORMATION_SCHEMA case fix (F12)

## 2026-06-12
- feat(from-tableau): v1.8.0 — static sets → column sets (BL-009 Phase 2a); detect+log Top-N/set-ops/set-actions as deferred; refresh thoughtspot-sets-tml.md with column-set/query-set vocabulary
- fix(mappings): trig unit bug — SIN/COS/TAN now convert radians→degrees (Tableau trig is radians, ThoughtSpot is degrees); UPPER/LOWER fixed to sql_string_op pass-through (no native in TS 26.6.0); REGEXP_MATCH fixed to sql_bool_op (returns boolean, not 1/0)
- feat(convert-from): PT1 cross-skill pass-through policy — scalar pass-throughs reliable; aggregate pass-throughs (sql_*_aggregate_op) must be flagged for review; policy in ts-model-conversion-invariants.md, applied across Tableau/SV/Databricks formula-translation files
- feat(from-tableau): v1.7.0 — Phase-1 Tableau function mappings: DATEPARSE, EXP, trig, STARTSWITH/ENDSWITH, PI/RADIANS/DEGREES composites, PROPER/ASCII/CHAR/REGEXP/FINDNTH pass-through, WINDOW_*/RUNNING_COUNT table-calc notes (BL-009 Phase 1)
- feat(validate): `check_tml.py` now enforces I4 (join id==name exact case) and I5 (no `aggregation: COUNT_DISTINCT` on physical columns); added `tools/validate/tests/test_check_tml.py` (BL-001)
- feat(convert-from): add an inline pre-import validation gate (I1/I2/I4/I5) to ts-convert-from-tableau, -snowflake-sv, and -databricks-mv before model TML import (BL-001)
- fix(mappings): Snowflake `BOOLEAN` maps to `BOOL` for ThoughtSpot — `ts tables create` rejects `BOOLEAN` on Snowflake connections (BL-006)
- chore(mirrors): mirror conversion invariants into the tableau + databricks-mv cursor rules, completing BL-012 parity

## 2026-06-11
- docs: add `ts-model-conversion-invariants.md` shared reference — canonical hard-rule checklist (I1–I7 + EXC1 + N1) for all Model-producing conversion skills; cross-linked from `thoughtspot-model-tml.md`
- feat: add `conversion-consistency-auditor` subagent — semantic auditor for I1–I7 and N1 across the five conversion skills plus their cursor + coco-snowsight mirrors (Mirror parity section); I3 is advisory (WARN); run before merging any conversion-skill PR
- fix(agents): update `consistency-checker` to current layout — scans `agents/cli/`, `agents/claude/`, and `agents/coco-snowsight/` (keeps `agents/claude/`-only skills like `ts-profile-snowflake` in coverage)
- feat(from-snowflake-sv): v1.5.0 — drop TEST_SV_ prefix, I5 explicit note, open-items.md
- feat(from-databricks-mv): v1.1.0 — preserve Spotter setting on in-place update, drop TEST_MV_ prefix
- fix(from-tableau): v1.5.39 — add I1–I6 hard rules to Step 5b, I7 formula-reference gate
- fix(mirrors): mirror the conversion invariants into the snowflake-sv cursor rule (v1.3.1) and coco-snowsight skill (v1.3.1) — I1–I6 + N1 callout and I7 gate, matching the CLI skill
- fix(validators): complete the `agents/claude/`→`agents/cli/` + `agents/coco/`→`agents/coco-snowsight/` rename left incomplete by PR #18. The validators (`check_references`, `check_skill_versions`, `check_skill_naming`, `check_yaml`, `check_patterns`, `check_smoke_tests`, `check_consistency`, `check_open_items`, `suggest_*`) globbed the old paths and were silently checking only 1 of 20 skills; they now scan `agents/cli/`, `agents/claude/`, and `agents/coco-snowsight/`. `check_references` now skips `{template}` placeholder link targets.
- docs(layout): fix stale `agents/claude/` / `agents/coco/` references across `.claude/rules/*`, `CLAUDE.md`, `agents/PARITY.md`, `agents/cursor/*`, `agents/coco-snowsight/CLAUDE.md`, `tools/` docs, and two cursor rule mirrors to the canonical `agents/cli/` + `agents/coco-snowsight/` layout (`agents/claude/` retained for the Claude-only `ts-profile-snowflake` annex)

## 2026-06-10
- feat: `ts-convert-from-tableau` v1.2.0 → v1.5.37 — major dashboard→liveboard migration upgrade, hardened against 6 real workbook migrations on a live ThoughtSpot. Adds Step 4.5 (confirm tables exist before searching; connection required, no placeholders), Step 5.5 (Spotter on every model), Step 7/7.5 (formula-review checkpoint + model confirmation), Step 9d (orphan-worksheet prompt), full liveboard generation (obj_id binding, complete chart blocks with resolved names, note tiles, KPI-per-measure, parameter header chips, Migration Summary tab, curated style themes), Step 11.5 (formula-coverage answers — every formula gets a testable answer), and Step 12 (written `MIGRATION_REPORT.md` with outcomes table, hyperlinks, and a full formula-mapping status table)
- docs: expand Tableau shared reference library — `tableau-formula-translation.md` (rank direction arg; `cumulative_*`/`moving_*` are query-time only and take the shelf attribute as sort arg; `concat()` not `+`; dynamic year-comparison; drop redundant pass-through formulas), `tableau-tml-rules.md` (in-place re-import requires top-level `guid`/`obj_id`), and schema docs (`thoughtspot-answer-tml.md` PERCENTAGE format; `thoughtspot-liveboard-tml.md` TABLE_MODE tiles omit the chart block)

## 2026-06-09
- feat: add `ts-convert-from-tableau` skill — convert Tableau workbooks (.twb/.twbx) into ThoughtSpot table + model TMLs with optional dashboard-to-liveboard migration; available in CLI, Cortex Code CLI, and Cursor
- docs: add Tableau shared reference library — formula translation (`tableau-formula-translation.md`) and TML generation rules (`tableau-tml-rules.md`) in `agents/shared/mappings/tableau/`
- chore: bump ts-cli to v0.8.0 — adds `--include-obj-id`, `--include-obj-id-ref`, `--no-guid` flags to `ts tml export` for export_options support

## 2026-06-01
- feat: add `ts metadata report` command — dependency walk + TML probes + risk classifier + formatters
- feat: rewrite ts-dependency-manager Steps 4/5 to delegate to `ts metadata report` CLI

## 2026-05-22
- feat: add `ts-convert-to-databricks-mv` and `ts-convert-from-databricks-mv` skills — convert between ThoughtSpot Models and Databricks Metric Views (v0.1 single-source and v1.1 multi-source); available in CLI, Cortex Code CLI, and Cursor
- feat: add `ts-profile-databricks` skill — manage Databricks connection profiles with Service Principal (OAuth M2M), PAT, or existing CLI profile auth; available in CLI, Cortex Code CLI, and Cursor
- docs: add Databricks Metric View shared reference library — MV YAML schema (`databricks-metric-view.md`), bidirectional mapping rules, formula translation reference, and property coverage matrix in `agents/shared/mappings/ts-databricks/`

## 2026-05-13
- feat: add `ts-recipe-formula-hms-display-snowflake` (v1.0.0) — deploys four Snowflake scalar UDFs (`format_seconds_to_hms`, `format_seconds_to_dhms`, `format_minutes_to_hm`, `format_minutes_to_dhm`) for formatting integer durations as `HH:MM:SS` / `DD:HH:MM:SS` / `HH:MM` / `DD:HH:MM` strings; shows ThoughtSpot `sql_string_op` formula syntax and TML pattern; available in CLI, Cortex Code CLI, Snowsight Workspaces, and Cursor
- refactor: introduce `ts-recipe-*` naming family for analytical capability skills — rename `ts-setup-snowflake-udfs-business-days` → `ts-recipe-formula-business-days-snowflake` (v2.0.0 MAJOR); update validator, skill-naming doc, smoke tests, README, and all SETUP.md files
- feat: split README "Setup" section into "Connection Profiles" (`ts-profile-*`) and "Recipes" (`ts-recipe-*`) for clearer category separation

## 2026-05-12
- feat: add `ts-setup-snowflake-udfs-business-days` (v1.0.0) — deploys three Snowflake scalar UDFs for weekday-only date arithmetic (`get_business_days_clamped`, `get_business_minutes_clamped`, `get_business_duration_str`) and shows ThoughtSpot `sql_int_op` / `sql_string_op` formula syntax; available in CLI, Cortex Code CLI, Snowsight Workspaces, and Cursor

## 2026-05-11
- chore: bump ts-cli to v0.6.0
- fix: `ts tml import` default changed from `--create-new` to `--no-create-new` — prevents silent duplicate creation when importing TML with an existing GUID; updated help text and docstring with explicit warning about the `--create-new` + existing-GUID pitfall
- fix: `ts tml export --type FEEDBACK` now exits immediately with a clear error explaining that feedback TML must be exported via the feedback object's own GUID (the API returns HTTP 400 for model GUID + type=FEEDBACK); directs user to `ts metadata dependents` to locate feedback GUIDs
- feat: `ts profiles list --snowflake` — lists Snowflake profiles from `~/.claude/snowflake-profiles.json` (name, method, account, warehouse); previously there was no CLI path to list Snowflake profiles
- fix: `ts-object-model-coach` Step 2b — replaced broken `--type FEEDBACK` export with the correct two-step approach: find feedback object GUIDs via `ts metadata dependents`, then export each GUID directly; handles zero-feedback models gracefully (proceeds with empty list)
- chore: bump ts-cli to v0.5.0 — adds `--type` flag to `ts tml export` for FEEDBACK TML export
- fix: migrate all direct urllib API calls in `ts-object-model-coach` to ts CLI (`ts tml export --type FEEDBACK`, `ts metadata dependents --raw`, `ts metadata dependents`); Cursor mirror updated to match (v1.2.0)

## 2026-05-05
- feat: add Mode C (update existing) to `ts-convert-from-snowflake-sv` (v1.4.0) and `ts-convert-to-snowflake-sv` (v1.2.0) — diff-and-confirm workflow for applying a changed SV/Model to an existing counterpart; per-column KEEP/UPDATE/MERGE decisions; `ai_context` and Data Model Instructions never touched; coaching handoff to `/ts-object-model-coach` after import. Mirrored in Cursor `.mdc` (v1.3.0 / v1.2.0) and CoCo runtimes (v1.3.0 / v1.2.0).
- feat: Mode B (split/merge) is now first-class in both conversion skill mode menus — previously a sub-flow triggered by domain detection, now an explicit choice at session start.
- docs: rename "reverse-engineer" → "convert" in all descriptions for `ts-convert-from-snowflake-sv` across Claude, Cursor, CoCo, README, and SETUP.md files.
- test: add `--mode-c` flag to `smoke_ts_from_snowflake.py` (verifies `--no-create-new` updates in-place, not duplicate) and `smoke_ts_to_snowflake.py` (verifies `CREATE OR REPLACE` on an existing SV).

## 2026-04-28
- feat: `ts-convert-from-snowflake-sv` adds Step 9.5 — confirm Spotter (AI search) enablement before import (default Y). Preserves the existing setting on in-place updates rather than silently overwriting. Mirrored in Cursor `.mdc` and CoCo runtimes.
- feat: SV ↔ TS metadata mapping — `with synonyms=(...)` now maps to display name + `properties.synonyms` (top-level `synonyms:` is silently dropped on TS import); per-dimension/metric `comment='...'` → column `description`; per-table `comment='...'` in the SV `tables(...)` block → TS Table TML `table.description`. Affects `ts-convert-from-snowflake-sv` and `ts-convert-to-snowflake-sv` across Claude/Cursor/CoCo runtimes.
- feat: semi-additive direction handling — `non additive by (col desc nulls last)` now translates to `first_value(...)` (previously documented as untranslatable); `asc nulls last` continues to translate to `last_value(...)`.
- fix: `count_distinct(...)` is rejected by the TS formula parser — `unique count` (with a space, not underscore) is the only valid form. Updated all references in `thoughtspot-formula-patterns.md`, `ts-snowflake-formula-translation.md`, and reverse-flow rules.
- fix: `+` does not concatenate strings in TS formulas — must use `concat(...)`. Documented in `thoughtspot-formula-patterns.md`.
- docs: add `ts-from-snowflake-dunder.md` worked example exercising multi-value synonyms, descriptions, table comments, semi-additive (closing/opening), `unique count`, and `concat()`. BIRD example unchanged.
- chore: add skill-naming convention rule + validator (`.claude/rules/skill-naming.md`, `tools/validate/check_skill_naming.py`) — six families documented (`ts-object-*`, `ts-profile-*`, `ts-convert-*`, `ts-dependency-*`, `ts-variable-*`, `ts-setup-*`); pre-commit fails if a skill name doesn't match a family or sit on the (currently empty) allowlist
- feat: rename `ts-coach-model` → `ts-object-model-coach` (skill bumped to v2.0.0) — aligns with the `ts-object-{type}-{verb}` family pattern; slash command, smoke-test filename, and cache directory all change
- chore: add runtime-coverage convention rule + validator (`.claude/rules/runtime-coverage.md`, `tools/validate/check_runtime_coverage.py`) — Cursor mirrors Claude; CoCo divergences documented in `EXPECTED_DIVERGENCES` map with per-entry justification; pre-commit fails on undocumented gaps
- feat: add Cursor mirrors for `ts-dependency-manager` and `ts-object-model-coach` (closes the previously-undetected gap where Claude had skills with no Cursor `.mdc`); both marked "Untested in Cursor" pending validation by a Cursor user

## 2026-04-27
- feat: add `ts-dependency-manager` skill (v1.0.0) — Audit / Remove / Repoint modes for safely changing columns across Models, Views, Answers, Liveboards, and Sets, with alias-aware dep walk, STOP-condition handling, TML backup, post-import verification, drift detection, and rollback
- feat: add `ts metadata dependents <guid>` to ts-cli (v0.4.0) — wraps v2 metadata/search with `include_dependent_objects=true`; default flat output (one row per dep) or `--raw` for the full v2 response
- feat: add `ts-variable-timezone` skill — manage `ts_user_timezone` variable at org and user level (Beta in 26.5, EA in 26.6)

## 2026-04-24
- feat: add skill versioning — every SKILL.md now has a `## Changelog` section with semver tracking
- feat: add interactive changelog prompt to pre-commit hook (`suggest_skill_version.py`)
- chore: move `semantic-layer-compare` skill to `semantic-layer-research` repo

## 2026-04-23
- feat: add cross-platform credential support (Windows/Linux) and Cursor agent runtime
- feat: add multi-domain split and multi-SV merge to conversion skills
- feat: redesign `ts-convert-to-snowflake-sv` to use native DDL creation (DROP YAML output)
- refactor: rename project from `thoughtspot-skills` to `thoughtspot-agent-skills`
- chore: add branching protocol rule (session-start check)

## 2026-04-22
- feat(ts-object-answer-promote): add parameter promotion — promote Answer parameters to Model alongside formulas (Abhijit Das)

## 2026-04-21
- refactor: add `ts-` brand prefix to all skill names
- refactor: rename `ts-object-model-promote` → `ts-object-answer-promote`
- refactor: restructure profile setup skills — profile before platform
