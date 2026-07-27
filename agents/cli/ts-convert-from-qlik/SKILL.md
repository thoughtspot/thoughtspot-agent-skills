---
name: ts-convert-from-qlik
description: Convert or import a Qlik Sense app into ThoughtSpot — parses a Qlik app (offline .qvf, or an exported Qlik Engine artifacts directory) into tables, columns, master measures and sheets, generates Table + Model TML and a tabbed Liveboard, translates Qlik measure expressions to ThoughtSpot formulas, validates and imports. Direction is always Qlik → ThoughtSpot. Not for ThoughtSpot → Qlik or standalone TML exports.
---

# Qlik Sense → ThoughtSpot

Converts a Qlik Sense app into ThoughtSpot objects through the `ts qlik` CLI: parse the app
(offline `.qvf` or a Qlik Engine artifacts directory) → build Table + Model TML → build a
tabbed Liveboard (one tab per Qlik sheet) → validate and import. Anything it cannot faithfully
translate — Set Analysis with current-selection state, Qlik variables, functions with no
ThoughtSpot equivalent — is flagged `NEEDS REVIEW` in the migration report, never silently
downgraded to a wrong-but-valid substitute.

Ask one question at a time for **dependent** decisions (where the next depends on the answer);
**batch independent** questions into a single prompt to keep the migration fast.

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/qlik/qlik-thoughtspot-formula-translation.md](../../shared/mappings/qlik/qlik-thoughtspot-formula-translation.md) | Qlik → ThoughtSpot formula/function mapping (199 rows). Consult before declaring any expression untranslatable. |
| [../../shared/schemas/qlik-app-ir.md](../../shared/schemas/qlik-app-ir.md) | The IR contract between `ts qlik parse` and build-model/build-liveboard |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure + critical invariants |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure |
| [../../shared/schemas/thoughtspot-answer-tml.md](../../shared/schemas/thoughtspot-answer-tml.md) | Answer/visualization TML structure |
| [../../shared/schemas/thoughtspot-liveboard-tml.md](../../shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure |
| [../../shared/schemas/thoughtspot-chart-types.md](../../shared/schemas/thoughtspot-chart-types.md) | Verified `answer.chart.type` enum |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [references/coverage-matrix.md](references/coverage-matrix.md) | Mapped/unmapped Qlik construct + expression matrix |
| [references/migration-report-format.md](references/migration-report-format.md) | Required `migration_report.md` format (+ [worked example](references/migration-report.example.md)) |
| [references/open-items.md](references/open-items.md) | Known quirks / unverified items |

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not.
- `ts` CLI installed: `pip install -e tools/ts-cli`. For the live modes (below), also install
  the Qlik extra: `pip install -e 'tools/ts-cli[qlik]'` (adds `websocket-client`).
- A Qlik source, one of four `--mode` values:
  - **`offline`** (default) — an offline **`.qvf`** app file. Recovers what it can (tables,
    columns, master measures, sheets) and flags what it cannot; no live Qlik connection.
  - **`engine-artifacts`** — a directory exported by the Qlik Engine API.
  - **`qlik-cloud`** — pulls exact definitions live from a Qlik Cloud tenant (**the
    foolproof, SOURCE-provenance path** — no guessing). Needs `--tenant <url> --app-id <guid|name>`
    and an API key (via `--api-key` or, preferred, the `QLIK_API_KEY` env var).
  - **`engine`** — a running Qlik Engine over websocket (`--engine <wss-url> --app-id <guid>`,
    optional repeatable `--header k=v`).
  Credentials are never entered in this conversation — the user sets `QLIK_API_KEY` (or passes
  `--api-key`) in their own terminal; the value is never echoed or written to a file.
- The source tables already exist in a warehouse and a ThoughtSpot connection exposes them.
  This skill creates ThoughtSpot *logical* objects (Table, Model, Liveboard) over existing
  physical tables; it does not load data. For a demo, `ts load` can provision synthetic tables.

## Workflow

### Step 0 — Parse
```bash
ts qlik parse <app.qvf> --output /tmp/qlik_inv.json
# or, from a Qlik Engine artifacts export:
ts qlik parse <artifacts-dir> --mode engine-artifacts --output /tmp/qlik_inv.json
# or, live from Qlik Cloud (foolproof path — needs QLIK_API_KEY set in the shell):
ts qlik parse --mode qlik-cloud --tenant <tenant-url> --app-id <guid|name> --output /tmp/qlik_inv.json
# or, live from a Qlik Engine websocket:
ts qlik parse --mode engine --engine <wss-url> --app-id <guid> --output /tmp/qlik_inv.json
```
`build-model` and `build-liveboard` accept the same `--mode` and connection flags, so the whole
chain can run against any source. The live modes give **SOURCE** provenance (exact definitions);
offline/engine-artifacts give best-effort extraction that flags gaps.
Emits tables, columns, master measures, master dimensions, sheets and charts, plus `counts`.
Read it; note any warnings (the parser flags what it could not read rather than guessing). An
opaque `.qvf` degrades to warnings and an empty-but-valid inventory — it never crashes.

### Step 1 — Build the model
```bash
ts qlik build-model <app.qvf> --connection "<TS connection>" \
  --db <DATABASE> --schema <SCHEMA> --model-name "<Model name>" --output out/ \
  [--overrides overrides.json] [--types wh_types.json] [--mode offline|engine-artifacts]
```
Emits Table TML(s) + Model TML + `mapping.json`. Master-measure expressions become formulas
(`[formula_<name>]` id-references, so they import in a single pass). Column data types come from
the warehouse type map (`--types`) when supplied, else are inferred from Qlik field types.
Set Analysis using current-selection (`$`) context, Qlik variables, and functions with no
ThoughtSpot equivalent are flagged `NEEDS REVIEW` — never faked. Read `mapping.json`.

### Step 2 — Validate & import the model
Lint, then import the tables + model, VALIDATE_ONLY first, then real:
```bash
ts tml lint out/*.tml
ts tml import out/*.table.tml out/*.model.tml --profile <name> --policy VALIDATE_ONLY
ts tml import out/*.table.tml out/*.model.tml --profile <name>
```
If the engine rejects a formula, drop it (and any column that depends on it) and re-import —
what lands is guaranteed to work, and the report records what was pruned.

### Step 3 — Build & import the liveboard
```bash
ts qlik build-liveboard <app.qvf> --model-name "<Model name>" --output out/ \
  [--model-fqn <model-guid>] [--report-name "<Liveboard name>"]
ts tml import out/*.liveboard.tml --profile <name>
```
Each Qlik sheet becomes a Liveboard tab; each chart becomes an embedded Answer whose search
query is built from the chart's dimensions and measures. Chart types with no ThoughtSpot
equivalent default to a table and are flagged.

### Step 4 — The hard tail
Set Analysis current-selection state and Qlik variables have no 1:1 ThoughtSpot path — recreate
them as Model formulas, parameters, or RLS as appropriate (see the coverage matrix). For an
expressible flagged measure, `ts spotter answer` can draft it from plain English; **verify the
numbers on the cluster before adopting** — never auto-adopt a Spotter answer.

### Step 5 — Migration report
`mapping.json` accounts for every table, measure, and chart with a status (Migrated /
Approximated / NEEDS REVIEW / Skipped). Render it into a `migration_report.md` following
[references/migration-report-format.md](references/migration-report-format.md) — keep the
section order and the exact status vocabulary — and hand that to the user as the deliverable.
Never silently drop a source object: every one appears in a table with a status.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-07-21 | Initial release — `ts qlik` parse / build-model / build-liveboard (Qlik Sense → ThoughtSpot) |
