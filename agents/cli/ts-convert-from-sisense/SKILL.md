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

> **MANDATORY (I7) — before classifying any JAQL formula as untranslatable, open
> [`../../shared/mappings/sisense/sisense-formula-translation.md`](../../shared/mappings/sisense/sisense-formula-translation.md)
> and check its `AGG_MAP` aggregation table, its `FUNCTION_MAP` function table, and the
> Approximated table. Do not decide from syntax alone.**
> See `../../shared/schemas/ts-model-conversion-invariants.md` (I7).

```bash
ts sisense build-model --input <bundle.json> --connection "<TS connection>" \
  --database <DATABASE> --schema <SCHEMA> --model-name "<Model name>" --out out/ \
  [--join-type LEFT_OUTER] [--lower-db-table] [--overrides overrides.json]
```
Emits Table TMLs + Model TML + `mapping.json`. Every join runs from the fact (MANY) side to
the dimension (ONE) side — the side carrying more distinct join keys is the fact, then fewer
shared keys, more measures, more relations, and table name — and carries the relation's
cardinality (default MANY_TO_ONE). The same bundle always yields the same join graph. Plain JAQL aggregations map via the aggregation map
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
widget answer. The dashboard filter bar becomes cross-viz Liveboard filter chips (member→`in`,
exclude→`not in`, numeric range→GE/GT/LE/LT/BW_INC/BW/EQ — see the worked example).

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

### Step 3 (alternative) — Bind to an EXISTING Model

Use this instead of Steps 1–3 when the Model already exists — designed by hand, or built
earlier from the same warehouse — and the dashboards must land on it. Export the Model WITH its
`obj_id` (the only exact viz binding: a Model can carry a custom obj_id no name derivation
reproduces), then build against it:

```bash
ts tml export <model-guid> --include-obj-id --profile <name> > target-model.json
ts sisense build-liveboard --input <bundle.json> --target-model target-model.json --out out/ \
  [--drill <drill-dashboard>.dash ...] [--overrides overrides.json] [--report-name "<name>"]
```

What it does, all deterministic:

| Sisense | ThoughtSpot |
|---|---|
| `[Table.column]` | The Model column exposing exactly that table instance + column. A role-playing copy (two date tables, two copies of one dimension) resolves by name, else by the **foreign-key column** the Sisense relation uses — never by bare column name |
| `count` (a DISTINCT count) | `unique count [X]`; over a key the Model hides, the Model formula `unique count ( [inst::col] )` |
| Widget-level filter | Search filter: members `[X] = 'a' [X] = 'b'` (ORed), excludes `[X] != 'a'` (ANDed), ranges `>= > <= <`. Never `in (...)` / `not in (...)` — search ignores both silently |
| WidgetsTabber (daily/weekly/… tabs) | The active tab's widget only, grain suffix dropped from its title; the other grains are the chart's own date-bucket control. Reported `Merged` |
| Value / axis titles | `custom_name` |
| Rich-text widget, tab-set title | Section-header note tile |
| Columnar layout | Tile grid (rows fill 12 columns; a merged tab's width goes to the kept one) |
| Jump-to-dashboard drill | A details table from the drill dashboard's widget (pass it with `--drill`), carrying the filters every source widget shares; users narrow it with right-click → Filter |
| Dashboard filter | Chip (`oper: in` / `not in`, top-level `values`). A chip on a column a tile filters itself lists that tile in `excluded_visualizations` (a chip REPLACES a tile's own filter; Sisense ANDs them). A dimension with several role copies binds to the copy reaching the most tiles, then the shortest join path |

Anything only the Model's author can decide is **NEEDS REVIEW** in `out/migration-report.json`
with the reason, and is resolved in `overrides.json` — never guessed:

```json
{"field_map":  {"[legacy_events.event_id]": "Event Count"},
 "filter_map": {"[Start_Date.id_]": "[Visit Started?] = true"}}
```

`field_map` binds a Sisense dim to a Model column (a source table the connection cannot see, a
formula field); `filter_map` replaces a Sisense filter with a search fragment (a filter on a key
the Model hides). Typical causes: a Sisense table missing from the Model, a hidden key, a filter
the Model expresses as a flag. Then lint, import and verify:

```bash
ts tml lint --dir out/
ts tml import --dir out/ --policy ALL_OR_NONE --profile <name>
ts tml verify-render <liveboard-guid> --profile <name>     # add --strict-data to gate on suspect tiles
```

`verify-render` lists `suspect_tiles`: a tile answering 0, nothing, or one all-NULL group. That is
the shape of a query that could not combine two facts — a measure filter on one fact with an
attribute from another returns no error, just a wrong 0. A real zero is possible, so read each one
against the source before accepting it.

### Step 4 — Migration report
`mapping.json` accounts for every table, measure, and widget with a status (Migrated /
Approximated / NEEDS REVIEW / Skipped), plus `warnings`. Hand it to the user as the
deliverable, calling out every NEEDS REVIEW row (window/time-intelligence formulas, unknown
widgets, unresolved fields) for manual rebuild.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.1.0 | 2026-10-27 | **Bind a dashboard to an existing Model (`build-liveboard --target-model`).** Fields resolve by table instance + column through role copies and relation keys; Sisense `count` is a distinct count; widget filters, tab sets, titles, rich text, layout and jump-to-dashboard drills are carried; chips use the exported-Liveboard shape (`in` / `not in`) with `excluded_visualizations`; `verify-render` lists suspect tiles. Viz binding uses the Model's exported `obj_id`, and a derived obj_id now drops parentheses and commas as the server does. Verified tile-for-tile against a hand-built rebuild of a 31-widget dashboard |
| 1.0.5 | 2026-10-22 | **An explicit many-to-many relation is no longer emitted as a join (BL-397).** ThoughtSpot rejects a `MANY_TO_MANY` Model join at import (error 14528), so it is left out and flagged NEEDS REVIEW, pointing at a warehouse bridge table. Sisense v2 bundles rarely carry cardinality; the default case is unchanged. |
| 1.0.4 | 2026-10-21 | **Join direction is deterministic and fact → dimension (ts-cli v0.179.0, BL-398).** The source side of each join was picked by a sort over a set, so on tied connection counts the join graph varied run to run and two facts sharing dimensions could fail `ts tml lint` I17. Tables are now ranked once (distinct join keys, shared keys, measures, connections, name). Coverage matrix updated |
| 1.0.3 | 2026-10-07 | **Quote-bearing literals and `a * b / c` are exact (ts-cli v0.165.0, BL-365).** A literal with a quote is emitted double-quoted (read SQL-standard: `''` is one quote), a backslash doubled, and every product under a division bracketed |
| 1.0.2 | 2026-10-06 | **2-arg `round` no longer imports as a wrong number (ts-cli v0.156.0, BL-331).** It was emitted verbatim and marked Approximated, but Approximated still imports: `round(x, 0)` was NULL on every row and `round(x, 2)` rounded to the nearest 2. A literal decimal count now converts to ThoughtSpot's increment (`2` → `0.01`) and is Migrated; a non-literal one is NEEDS REVIEW. Coverage matrix updated |
| 1.0.1 | 2026-09-22 | **I7 untranslatable gate added.** Step 1 flagged JAQL formulas NEEDS REVIEW with no instruction to open [sisense-formula-translation.md](../../shared/mappings/sisense/sisense-formula-translation.md) first. Now gated by `check_i7_gate.py`, which requires the literal `MANDATORY (I7)` marker in a blockquote citing this skill's own dialect mapping and the invariants doc (2026-09-22 audit finding 9.3). |
| 1.0.0 | 2026-07-17 | Initial release — `ts sisense` parse / build-model / build-liveboard |
