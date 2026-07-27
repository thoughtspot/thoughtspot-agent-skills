# Open Items — ts-convert-from-qlik

Tracks unverified behaviour, deferred work, and known gaps.
Status: OPEN | VERIFIED | DEFERRED | WONT-FIX

---

## #1 — End-to-end import against a live ThoughtSpot instance — OPEN

**Question:** Does the full `parse → build-model → tml import → build-liveboard → tml import`
chain round-trip on a live cluster (model imports, formulas resolve, liveboard renders)?

**Status:** The generated TML is unit-tested for structure and honours the critical invariants
(db_column_name, connection name-only, formula_id linkage, aggregation only in columns[]), and
`ts tml lint` passes on the output. A live-instance import has **not** yet been run — no live
Qlik + ThoughtSpot pair was available at authoring time. Verify before relying on it in a
customer migration; capture the finding here.

## #2 — Chart-type enum validity — OPEN

**Question:** Do all mapped `answer.chart.type` values emitted by `ts qlik build-liveboard`
match the accepted enum in `thoughtspot-chart-types.md` on the target build (e.g. tables must be
`GRID_TABLE`, not `TABLE`; no `COMBO`)?

**Status:** The mapping targets documented enum values and defaults unknown types to a grid
table with a flag. Confirm each emitted type imports without an "invalid chart type" error on a
live cluster.

## #3 — Table joins / associations on the offline path — DEFERRED

A `.qvf` does not expose a dependable association graph, so `build-model` emits the Model with
tables bound but `model_tables[].joins` empty (coverage-matrix U4). Recovering associations from
`--mode engine-artifacts` (they are currently recorded only as info notes) and/or accepting a
join spec via `--overrides` is deferred to a follow-up.

## #4 — Promote the formula-translation reference to a shared mapping — DONE

The prose mapping now ships at
`agents/shared/mappings/qlik/qlik-thoughtspot-formula-translation.md` (199 rows, currency
anchor, passes `check_formula_catalog`). Adopting it caught and fixed a real error: `Upper`/`Lower`
were mapped to native `upper()`/`lower()` (which ThoughtSpot lacks) — corrected to the
`sql_string_op` passthrough in the doc, the formula-map data, and the translator (`functions.py`).

## #6 — Live Qlik Cloud / Engine extraction verified only against mocks — OPEN

**Question:** Do `--mode qlik-cloud` and `--mode engine` work against a real Qlik Cloud tenant /
running engine — actual REST item + data-connection shapes, QIX auth headers, name→GUID
`resolve_app_id`, websocket connect, and the Engine call sequence
(OpenDoc/GetScript/CreateSessionObject/GetLayout/GetObject/GetTablesAndKeys)?

**Status:** Both live paths are covered by 18 mocked/recorded-response unit tests (no network);
the offline + engine-artifacts paths need no live Qlik. Real Engine responses may vary by Qlik
build. Verify against a live Qlik Cloud tenant before relying on the live modes in a customer
migration; capture the finding here. Requires the `[qlik]` extra (`websocket-client`).

## #5 — Skill-level smoke test — DONE (offline)

`tools/smoke-tests/smoke_ts_convert_from_qlik.py` runs the full offline pipeline
(`ts qlik parse → build-model → tml lint → build-liveboard`) over the bundled
`SqliteApp.qvf` fixture and asserts real TML + mapping.json, lint-clean. No live
connection. `ts-convert-from-qlik` is no longer on the `check_smoke_tests` ALLOWLIST.
A live-import smoke (`--validate-only` against a real cluster) still depends on #1.
