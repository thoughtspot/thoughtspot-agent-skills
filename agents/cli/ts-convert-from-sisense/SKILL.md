---
name: ts-convert-from-sisense
description: Convert or import a Sisense dashboard into ThoughtSpot — parses a captured OFFLINE Sisense bundle JSON ({dashboard, widgets, datamodel}), generates Table + Model TML and Answers/tabbed Liveboard, translates JAQL (aggregations + the deterministic formula subset), validates and imports. Direction is always Sisense → ThoughtSpot. Not for ThoughtSpot → Sisense, and not a live Sisense fetch — the input is a bundle already on disk.
---

# Sisense Dashboard → ThoughtSpot

Converts a captured Sisense bundle into ThoughtSpot objects through the `ts sisense` CLI:
parse the offline bundle JSON (`{dashboard, widgets, datamodel}`) → build Table + Model TML →
build Answers and one tabbed Liveboard → validate and import. Anything it cannot faithfully
translate is flagged for a human in the migration report (`mapping.json`), never silently
downgraded.

The input is an **offline bundle already on disk** — there is no live Sisense REST fetch
(that is an open item). Capture `{dashboard, widgets, datamodel}` from Sisense first, then
point the CLI at that file.

Ask one question at a time for **dependent** decisions (where the next depends on the answer);
**batch independent** questions into a single prompt to keep the migration fast.

## References

| File | Purpose |
|---|---|
| [../../shared/mappings/sisense/sisense-formula-translation.md](../../shared/mappings/sisense/sisense-formula-translation.md) | JAQL → ThoughtSpot formula and function mapping |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure + critical invariants |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure |
| [../../shared/schemas/thoughtspot-answer-tml.md](../../shared/schemas/thoughtspot-answer-tml.md) | Answer/visualization TML structure |
| [../../shared/schemas/thoughtspot-liveboard-tml.md](../../shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML structure |
| [../../shared/schemas/thoughtspot-chart-types.md](../../shared/schemas/thoughtspot-chart-types.md) | Verified `answer.chart.type` enum |
| [../../shared/worked-examples/sisense/numeric-range-filter-to-chip.md](../../shared/worked-examples/sisense/numeric-range-filter-to-chip.md) | Dashboard numeric-range filter → Liveboard filter chip preset |
| [../../shared/worked-examples/sisense/date-bucket-granularity.md](../../shared/worked-examples/sisense/date-bucket-granularity.md) | Sisense date `level` → ThoughtSpot date bucket |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth setup |
| [references/coverage-matrix.md](references/coverage-matrix.md) | Mapped/unmapped JAQL + widget construct matrix |
| [references/open-items.md](references/open-items.md) | Known quirks / unverified items |

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not.
- `ts` CLI installed: `pip install -e tools/ts-cli`.
- A captured **offline Sisense bundle JSON** on disk — a single `{dashboard, widgets,
  datamodel}` object. The datamodel side (`datasets[].schema.tables[]` + `relations[]`) is
  what the model path needs; `dashboard` + `widgets` drive the liveboard. There is **no live
  Sisense fetch** — assemble the bundle from a Sisense export first (open-item #3).
- The source tables already exist in a warehouse and a ThoughtSpot connection exposes them.
  This skill creates ThoughtSpot *logical* objects (Table, Model, Answers, Liveboard) over
  existing physical tables; it does not load data.

## Workflow

### Step 0 — Parse
```bash
ts sisense parse --input <bundle.json> --output /tmp/sisense_inv.json
```
Emits tables, columns, relations (from the datamodel) plus a best-effort parse of widgets
and dashboard filters. Read it; note any `warnings` (the parser flags what it could not
confidently read rather than guessing).

### Step 1 — Build the model
```bash
ts sisense build-model --input <bundle.json> --connection "<TS connection>" \
  --database <DATABASE> --schema <SCHEMA> --model-name "<Model name>" --out out/ \
  [--join-type LEFT_OUTER] [--lower-db-table] [--overrides overrides.json]
```
Emits Table TMLs + Model TML + `mapping.json`. The most-connected table becomes the fact;
joins carry the relation's cardinality. Plain JAQL aggregations map via the aggregation map
(`sum`→SUM, `avg`→AVERAGE, …); calculated-column formulas translate through the deterministic
JAQL subset. Window / time-intelligence / population-stats / R are flagged NEEDS REVIEW —
never faked. `--lower-db-table` lowercases `db_table` for Databricks (folds unquoted names).
Read `mapping.json`.

### Step 2 — Validate & import the model
Lint locally first (structural invariants the server accepts silently), then import:
```bash
ts tml lint --dir out/
ts tml import --dir out/ --order tableau --policy ALL_OR_NONE --profile <name>
```
`--order tableau` imports tables before the model. If the engine rejects a formula, drop it
(and any column that depends on it) and re-import — what lands is guaranteed to work, and the
report records what was pruned.

### Step 3 — Build the liveboard
```bash
ts sisense build-liveboard --input <bundle.json> --model-name "<Model name>" --out out/ \
  [--model-fqn <model-guid>] [--report-name "<Liveboard name>"] \
  [--connection "<TS connection>"] [--database <DATABASE>] [--schema <SCHEMA>] \
  [--join-type LEFT_OUTER] [--lower-db-table] [--overrides overrides.json]
```
Widgets become Answers on the tabbed Liveboard: the Sisense widget type picks the chart
(`chart/column`→COLUMN, `indicator`→KPI, `pivot`→PIVOT_TABLE, …); JAQL panels map to roles
(Categories→x, Break-by→color, Values→y); a date `level` becomes a matching date bucket
(`months`→MONTHLY) so it sorts chronologically; a per-attribute top-N is baked into the
widget answer. The dashboard filter bar becomes cross-viz Liveboard filter chips (member→IN,
exclude→NOT_IN, numeric range→GE/GT/LE/LT/BW_INC/BW/EQ — see the worked example).

Each Answer is emitted via the shared emitter's `build_answer` using the Sisense-resolved
chart type directly, so the widget-type mapping wins and the Approximated / NEEDS REVIEW
signal survives into the report (a widget that can't be mapped is flagged, never silently
downgraded). Lint, then import the emitted TML:
```bash
ts tml lint --dir out/                                    # now includes the liveboard
ts tml import --dir out/ --order tableau --policy ALL_OR_NONE --profile <name>
ts tml verify-render <liveboard-guid> --profile <name>    # post-import gate; exit 1 = broken board
```

> **Why lint again here.** Step 2's lint runs before the liveboard is emitted, so it
> cannot see the tile — the same ordering gap found in the Qlik skill (audit finding
> 17.3). This converter routes through the shared `build_answer`, which already sets
> `axis_configs`, so nothing is expected to fire; the gate is here so a future change to
> the shared emitter cannot ship blank boards unnoticed.

### Step 4 — Migration report
`mapping.json` accounts for every table, measure, and widget with a status (Migrated /
Approximated / NEEDS REVIEW / Skipped), plus `warnings`. Hand it to the user as the
deliverable, calling out every NEEDS REVIEW row (window/time-intelligence formulas, unknown
widgets, unresolved fields) for manual rebuild.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-07-17 | Initial release — `ts sisense` parse / build-model / build-liveboard |
