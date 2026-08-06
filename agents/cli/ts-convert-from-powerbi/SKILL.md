---
name: ts-convert-from-powerbi
description: Convert or import a Power BI report into ThoughtSpot — parses the Power BI Project (.pbip) TMDL semantic model and PBIR report, generates Table + Model TML and Answers/tabbed Liveboards, translates DAX (including CALCULATE(ALL) → group_aggregate, and time-intelligence rebuilt with parameters), validates and imports. Direction is always Power BI → ThoughtSpot. Not for ThoughtSpot → Power BI or standalone TML exports.
---

# Power BI Report → ThoughtSpot

Converts a Power BI Project into ThoughtSpot objects through the `ts powerbi` CLI: parse the
`.pbip` (TMDL model + PBIR report) → build Table + Model TML → build Answers and one tabbed
Liveboard → validate and import. Anything it cannot faithfully translate is flagged for a
human in the migration report, never silently downgraded.

Ask one question at a time for **dependent** decisions (where the next depends on the answer);
**batch independent** questions into a single prompt to keep the migration fast.

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/powerbi/powerbi-formula-translation.md](../../shared/mappings/powerbi/powerbi-formula-translation.md) | DAX → ThoughtSpot formula and function mapping |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure + critical invariants |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure |
| [../../shared/schemas/thoughtspot-answer-tml.md](../../shared/schemas/thoughtspot-answer-tml.md) | Answer/visualization TML structure |
| [../../shared/schemas/thoughtspot-liveboard-tml.md](../../shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure |
| [../../shared/schemas/thoughtspot-chart-types.md](../../shared/schemas/thoughtspot-chart-types.md) | Verified `answer.chart.type` enum |
| [../../shared/worked-examples/powerbi/sply-parameter.md](../../shared/worked-examples/powerbi/sply-parameter.md) | Time-intelligence (SPLY/YoY) via a Reference Date parameter |
| [../../shared/worked-examples/powerbi/calculate-all-to-group-aggregate.md](../../shared/worked-examples/powerbi/calculate-all-to-group-aggregate.md) | `CALCULATE(m, ALL(col))` → `group_aggregate` |
| [../../shared/worked-examples/powerbi/combo-dual-axis-custom-chart-config.md](../../shared/worked-examples/powerbi/combo-dual-axis-custom-chart-config.md) | Combo line + column dual axis |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [references/coverage-matrix.md](references/coverage-matrix.md) | Mapped/unmapped DAX + visual construct matrix |
| [references/open-items.md](references/open-items.md) | Known quirks / unverified items |

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not.
- `ts` CLI installed: `pip install -e tools/ts-cli`.
- A Power BI **Project (`.pbip`)** folder on disk (TMDL + PBIR). A binary `.pbix` must be
  saved as `.pbip` in Power BI Desktop first (Windows; one-time), or extracted with
  `pbi-tools extract`.
- The source tables already exist in a warehouse and a ThoughtSpot connection exposes them.
  This skill creates ThoughtSpot *logical* objects (Table, Model, Answers, Liveboard) over
  existing physical tables; it does not load data. For a demo, `ts load databricks` can
  provision synthetic tables aligned to the model.

## Core rule — tiles come from the tool, never by hand

Every Answer/Liveboard tile is produced by `ts powerbi build-liveboard`. **Never hand-author
answer or liveboard TML, and never hand-edit a tile's `search_query`, `answer_columns`, or
chart block.** A hand-authored tile fails in one of two silent ways: a raw column reference
(e.g. `[Month]` instead of the `Month(Date)` bucket) fails at render with *"No data source
found for the query"*; and a chart tile with **no axis config** *loads data* (the board returns
200) but draws a **blank chart**. Either way the board looks done and shows empty tiles. If a
tile needs a measure that is not in the model yet, the fix is to add that measure to the
**model** (Step 3) and re-run `build-liveboard` — not to draw the tile by hand. Linting the
liveboard TML (Step 4, before import) catches the missing-axis case, and `ts tml verify-render`
(Step 4, after import) catches both, so a board that does not truly render is never handed over.

## Workflow

### Step 0 — Parse
```bash
ts powerbi parse <path-to-.pbip> --output /tmp/pbi_model.json
```
Emits tables, columns, measures, relationships, pages, visuals. Read it; note any warnings
(the parser flags what it could not read rather than guessing).

### Step 1 — Build the model
```bash
ts powerbi build-model <path-to-.pbip> --connection "<TS connection>" \
  --db <DATABASE> --schema <SCHEMA> --model-name "<Model name>" --output out/ \
  [--overrides overrides.json] [--lower-db-table]
```
Emits Table TMLs + Model TML + `mapping.json`. Joins carry the file's real cardinality; DAX
measures/calc-columns become formulas (`[formula_<name>]` id-references, topologically
ordered, with a cascade that flags anything depending on an un-migrated measure). Aggregation
follows `summarizeBy` (AVG vs SUM). Time-intelligence / point-in-time / iterators are flagged
NEEDS REVIEW — never faked. Read `mapping.json`.

### Step 2 — Validate & import the model
Lint and import the tables + model, VALIDATE_ONLY first, then real:
```bash
ts tml lint out/*.tml
ts tml import out/*.table.tml out/*.model.tml --profile <name> --policy VALIDATE_ONLY
ts tml import out/*.table.tml out/*.model.tml --profile <name>
```
If the engine rejects a formula, drop it (and any column that depends on it) and re-import —
what lands is guaranteed to work, and the report records what was pruned.

### Step 3 — Resolve the hard tail INTO the model (before the liveboard)
The liveboard tiles reference these measures, so they must exist in the model **first**.
Building the liveboard against a model still missing them is exactly what produces blank,
non-rendering tiles — resolve them here, re-import (Step 2), and only then build the liveboard.

- **`CALCULATE(m, ALL(dims))`** → `group_aggregate` (worked example) — already emitted by Step 1.
- **SAMEPERIODLASTYEAR / YoY** are flagged NEEDS REVIEW, never faked. Rebuild them
  deterministically with `ts powerbi build-timeintel` — it emits a `Reference Date` parameter
  plus `sum_if` reference-year / SPLY / YoY / YoY% measures (the pattern verified live; it is
  **measure-based**, so the tiles that reference them render — a hand-authored period-comparison
  tile does not) and merges them into the model TML:
  ```bash
  ts powerbi build-timeintel --specs timeintel.json --date-column "<Date column>" \
    --model out/*.model.tml
  ```
  `timeintel.json` is `[{"base_name": "New Hires", "base_expr": "[formula_isNewHire]"}, ...]`,
  where `base_expr` is the base measure's row-level body (from `mapping.json`); add
  `sply_name` / `yoy_name` / `yoy_pct_name` to match the source measure names so the author's own
  `YoY % Change` measures cascade through the id-references. **Verify the per-period numbers
  against the Power BI source before adopting** — the helper never invents numbers. For a
  one-off exploratory answer, `ts spotter answer` drafts the native `vs` period comparison.
- Re-import the model (Step 2). Do **not** proceed to the liveboard until every measure a tile
  will reference exists in the model.

### Step 4 — Build, import & VERIFY the liveboard
```bash
ts powerbi build-liveboard <path-to-.pbip> --model-name "<Model name>" --output out/
ts tml lint out/*.liveboard.tml                          # pre-import: flags any blank chart tile
ts tml import out/*.liveboard.tml --profile <name>
ts tml verify-render <liveboard-guid> --profile <name>   # REQUIRED gate; exit 1 = broken board
```
`build-liveboard` emits renderable tiles: report pages become tabs (PBI `pageOrder`; a Tooltip
page is dropped), role-aware axes (Category → x, Series/Legend → color, matrix Rows/Columns →
pivot, measures → y), a month column becomes a monthly date bucket (`Month(Date)`), and every
chart carries its axis config. **`ts tml verify-render` is a required gate, not optional.** It
also fails on a chart tile with no axis config (`blank_chart_tiles`) — a board can return data
yet draw blank. If
it reports `ok:false` it names the failing tile(s); the cause is almost always a tile
referencing a measure not in the model (return to Step 3) or a hand-edited tile. Fix the model
or re-run `build-liveboard` — never hand-edit the tile TML to silence the error.

### Step 5 — Migration report
`mapping.json` accounts for every table, measure, and visual with a status (Migrated /
Approximated / NEEDS REVIEW / Skipped). Note whether `verify-render` passed. Hand it to the
user as the deliverable.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.1.2 | 2026-08-03 | Render-robustness follow-up: lint the liveboard TML **before** import (Step 4) and let `ts tml verify-render` fail on the blank-chart case. A chart tile emitted with a type but no `chart.axis_configs` (or `custom_chart_config`) imports cleanly and **returns data (HTTP 200) yet draws blank** — the exact hole a hand-authored board fell through (a real board came back with 3 of 4 tiles blank). `ts tml lint` now flags such a tile pre-import and `verify-render` reports it under a new `blank_chart_tiles` field and exits non-zero, so a board that loads data but does not truly render can no longer pass the gate. Core rule reworded to name both failure modes (raw column → "No data source found"; no axis config → 200-but-blank). ts-cli v0.131.0. |
| 1.1.1 | 2026-07-30 | **BL-171 — `_DAX_FUNC` stops emitting seven non-existent or wrong-meaning ThoughtSpot names (ts-cli v0.126.1).** `TRIM`/`UPPER`/`LOWER` mapped to bare `trim`/`upper`/`lower`, `HOUR`/`MINUTE`/`SECOND` to bare `hour`/`minute`/`second`, and `DISTINCTCOUNT` to `unique_count` — **none of those seven names exists in the ThoughtSpot formula parser** (live-disproved on se-thoughtspot: `upper`/`lower` 2026-06-13, the rest 2026-07-30), so every affected measure failed at import with `error_code 14516`. Now: `TRIM`/`UPPER`/`LOWER` → `sql_string_op("TRIM({0})", …)` pass-throughs (via the shared `wrap_passthrough_calls`), `HOUR` → `hour_of_day`, `DISTINCTCOUNT` → `unique count` (with a space), and `MINUTE`/`SECOND` are **flagged NEEDS REVIEW** rather than faked — ThoughtSpot has no minute/second extractor and the warehouse dialect isn't known at this layer. Separately, `MONTH` mapped to `month`, which exists but returns the month **name**; DAX `MONTH()` is numeric, so the target is `month_number` — a wrong *number*, not a failed import. Coverage matrix updated; 9 new tests; existing `test_distinctcount_maps_to_unique_count` had asserted the wrong expectation and is corrected. **All emitted forms live-verified on se-thoughtspot 2026-07-30** (`VALIDATE_ONLY`, nothing persisted). |
| 1.1.0 | 2026-07-27 | Render-robustness: require `ts tml verify-render` as a gate after import; resolve the time-intelligence hard tail INTO the model before building the liveboard, via the new deterministic `ts powerbi build-timeintel` (Reference-Date SPLY/YoY measures, the live-verified measure-based pattern); add the "tiles come from the tool, never by hand" core rule (a hand-authored tile imports but fails to render with "No data source found") |
| 1.0.0 | 2026-07-16 | Initial release — `ts powerbi` parse / build-model / build-liveboard |
