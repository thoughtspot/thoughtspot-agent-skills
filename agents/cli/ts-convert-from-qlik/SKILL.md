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
ts tml lint out/*.liveboard.tml                          # pre-import: flags any blank chart tile
ts tml import out/*.liveboard.tml --profile <name>
ts tml verify-render <liveboard-guid> --profile <name>    # post-import gate; exit 1 = broken board
```

> **Why the lint line is here and not in Step 2.** Step 2 lints `out/*.tml` *before the
> liveboard exists*, so it never sees the tile. The `chart_tiles_missing_axis` rule
> (a chart type that needs an axis carrying neither `axis_configs` nor
> `custom_chart_config` imports cleanly and renders **blank**) therefore had no gate on
> this path at all — and this was the one converter whose builder violated it, so its
> boards shipped empty (audit finding 17.3; emitter fixed in the same change).
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
| 1.0.2 | 2026-07-30 | **BL-171 — end-to-end audit of the Qlik function map: six defect classes, all fixed (ts-cli v0.126.1).** v1.0.1 corrected eleven rows in `qlik-thoughtspot-formula-translation.md` and changed no code — and it turned out the *machine-readable* map the CLI actually loads (`qlik/data/qlik_ts_formula_map.json`) had not been updated either, so `ts qlik` served the pre-correction mapping. Every one of the 199 rows and every `FUNCTION_MAP` entry has now been audited against `thoughtspot-formula-patterns.md` and **live-probed on se-thoughtspot (2026-07-30, `VALIDATE_ONLY`, nothing persisted)**. Fixed: (1) `Trim`/`LTrim`/`RTrim`/`Replace` emitted bare names that do not exist → `sql_string_op` pass-throughs (`Upper`/`Lower` were already rewritten by a post-pass and were never actually broken); (2) `Len`/`Mid` were **identity-mapped to `len`/`mid`, which are not ThoughtSpot functions at all** → `strlen`/`substr`; (3) `MonthStart`/`QuarterStart`/`YearStart`/`WeekStart` emitted fabricated `date_trunc_*` names and `Day` emitted `day_of_month` → `start_of_*` / `day`; (4) `Ceil`/`Pow`/`Log` emitted `ceiling`/`power`/`log`, all three rejected by the parser → `ceil`/`pow`/`ln`; (5) `Count(DISTINCT x)` emitted `unique_count(` — the function has a **space**, `unique count(` — the underscore form is rejected; (6) Qlik `Concat()` **aggregates across rows** (like `GROUP_CONCAT`) and was silently name-mapped to row-level `concat()`, a valid-but-wrong formula, so it is now flagged NEEDS REVIEW per the skill's own flag-don't-downgrade contract. Doc rows S01/S09/D04/D08/D09/D10/D27/N09 were also wrong and are corrected (`exp()` **does** exist; `quarter`/`hour`/`minute`/`second`/`date_trunc` do not). The JSON and the markdown are now in step, and a new test (`TestSharedReferenceSync`) asserts they stay that way. Three more rows were wrong in the same wrong-meaning way and are corrected: `Mid` (Qlik is 1-indexed, ThoughtSpot `substr` is **zero**-indexed, so the start is now decremented — a bare rename imported and returned strings shifted one character), `Weekday` (Qlik returns a **number** from 0=Mon; `day_of_week` returns the day NAME and `day_number_of_week` starts at 1, so the origin is shifted) and `Month` (`month` returns the month NAME; `month_number` is 1-12). `Index` and `NetworkDays` were also reconciled — the first was documented as having no equivalent when `strpos` is exact for the default 1st-occurrence form, the second was mapped to `diff_days`, which counts calendar days and is not a business-day difference, so it is flagged. **How a flagged formula behaves:** it is written into the Model TML unchanged, with its `/* TODO review */` marker or original text, and **will fail at import until a human rewrites it** — loud by design, and the opposite of the `Concat()` behaviour it replaces, which imported silently and returned the wrong answer. `tests/test_qlik_functions.py` is new — 42 tests, including three self-detection guards: every mapped name must be a verified ThoughtSpot function, the packaged JSON must match this markdown row-for-row, and `FUNCTION_MAP` must name the same function as the mapping row (the assertion that catches the wrong-meaning class, which the other two pass happily). |
| 1.0.1 | 2026-07-29 | **BL-170 — eight rows corrected (docs only; CLI fix is BL-171).** Live verification on se-thoughtspot 2026-07-29 proved `trim`, `ltrim`, `rtrim`, `replace`, `starts_with` and `ends_with` are **all** absent from the ThoughtSpot formula parser. In `qlik-thoughtspot-formula-translation.md`: S05/S06/S07 (`Trim`/`LTrim`/`RTrim`) now map to `sql_string_op` pass-throughs — the previous entries were doubly wrong, recommending a two-sided `trim()` that does not exist; S11/S15/SC06 (`Replace`/`PurgeChar`/`MapSubString`) moved to the `REPLACE` pass-through, with `PurgeChar`'s chaining now inside one passthrough; S23/S24 became the `strpos ( ) = 1` and `substr`-`strlen` compositions; and CL06/CL07 (`Match`/`Not Match`) were corrected from `in (...)` to `in {...}` plus `not ( ... in { } )`. **Caveat: `ts_cli/qlik/functions.py` still emits the bare names — and `upper`/`lower` too — so affected formulas fail at import until BL-171 lands.** |
| 1.0.0 | 2026-07-21 | Initial release — `ts qlik` parse / build-model / build-liveboard (Qlik Sense → ThoughtSpot) |
