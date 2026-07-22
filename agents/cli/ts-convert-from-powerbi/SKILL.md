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

### Step 3 — Build & import the liveboard
```bash
ts powerbi build-liveboard <path-to-.pbip> --model-name "<Model name>" --output out/
ts tml import out/*.liveboard.tml --profile <name>
```
Report pages become tabs (PBI `pageOrder` preserved); a Tooltip page is dropped, not a tab.
Role-aware axes: Category → x, Series/Legend → color, matrix Rows/Columns → pivot axes,
measures → y. A month column becomes a monthly date bucket so it sorts chronologically.

### Step 4 — Time-intelligence and the hard tail
SAMEPERIODLASTYEAR / YoY have no 1:1 DAX→formula path — rebuild them with a **Reference Date
parameter** (see the worked example). `CALCULATE(m, ALL(dims))` is auto-translated to
`group_aggregate` (worked example). For an expressible flagged measure, `ts spotter answer`
can draft it from plain English; **verify the numbers on the cluster before adopting** — never
auto-adopt a Spotter answer.

### Step 5 — Migration report
`mapping.json` accounts for every table, measure, and visual with a status (Migrated /
Approximated / NEEDS REVIEW / Skipped). Hand it to the user as the deliverable.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-07-16 | Initial release — `ts powerbi` parse / build-model / build-liveboard |
