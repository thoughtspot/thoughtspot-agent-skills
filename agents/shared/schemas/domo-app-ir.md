<!-- currency: domo — 2026-07 (ts domo IR v0.1) -->

# Domo App IR — the extract↔transform contract

The **intermediate representation (IR)** is the single contract between the Domo-extraction side
and the ThoughtSpot-transform side of the `ts domo` converter. Extractors (`domo-cloud` live API,
`offline` captured-bundle directory) populate these structures; `ts domo build-model` /
`build-liveboard` consume them. The IR is plain JSON — dump it, inspect it, hand-edit it, and
re-run later stages without touching Domo again.

Source of truth: `tools/ts-cli/ts_cli/domo/ir.py`. Every field is optional-friendly — a
best-effort extraction fills what it can and leaves the rest empty rather than failing.

## Why an IR at all (Domo is 4 endpoints, not one file)

Unlike a single Sisense bundle, a Domo "app" is assembled from **four distinct API objects**
(each has a matching offline fixture):

| Domo object | Live endpoint | Offline fixture | IR target |
|---|---|---|---|
| Dataset schema | `GET /v1/datasets/{id}/schema` | `domo_table_*.json` | `Dataset` |
| Beast Modes | `GET .../beastmode` (get-all) | `domo_model_beastmodes.json` | `BeastMode` |
| Card definition | get-chart-card-definition | `domo_card_*.json` | `Card` |
| Page | retrieve-a-page | `domo_liveboard_page_*.json` | `Page` |

The **offline "bundle" is a directory** of these JSONs (the fixture set is the reference layout);
the live mode calls the four endpoints. `parse` normalises either into one `DomoApp` IR.

## Root: `DomoApp`

| Field | Type | Notes |
|---|---|---|
| `app_name` | str | Derived from the page name, or `"Untitled"` |
| `source` | str? | Bundle directory or tenant URL |
| `extraction_mode` | str | `offline` \| `domo-cloud` (records extract fidelity) |
| `datasets` | `Dataset[]` | Domo datasets → TS tables |
| `beast_modes` | `BeastMode[]` | Global calculated fields (get-all-beast-modes) |
| `cards` | `Card[]` | Card definitions → TS answers |
| `pages` | `Page[]` | Pages → TS liveboards (one per page) |
| `notes` | `ExtractionNote[]` | Anything the extractor could not fully recover |

Serialization mirrors the family: `to_json()`, `save(path)`, `load(path)`, `from_dict(d)`;
`from_dict` tolerates unknown/missing keys so hand-edited IR and future fields never hard-fail.

## Nested structures

**`Dataset`** — `id` (Domo dataset guid), `name`, `description?`, `rows?`, `owner?`,
`columns[DatasetColumn]`.
**`DatasetColumn`** — `name`, `domo_type` (`STRING`\|`DATETIME`\|`DOUBLE`\|`LONG`), mapped to
TS `data_type` + `column_type` later (see the Beast Mode mapping doc's type table).

**`BeastMode`** — `id` (int), `name`, `formula` (Domo SQL-like, backtick-quoted column refs),
`data_source_id` (→ `Dataset.id`), `global` (bool), `status`, `linked_card_ids[]` (from `links[]`
where `resource.type == CARD`).

**`Card`** — `urn` (str, = page `cardIds` entry), `title`, `chart_type`
(`kpi`\|`bar`\|`table`\|…), `data_set_id` (→ `Dataset.id`), `calculated_fields[CalcField]`
(card-local copies of Beast Modes — handle global OR local), `query[CardQuery]`,
`conditional_formats[]`, `quick_filters[]`, `pref_width?`, `pref_height?`.
**`CalcField`** — `id`, `name`, `formula`, `save_to_dataset` (bool).

**`CardQuery`** — normalised from EITHER `summaryNumber` (KPI cards) OR `chartBody`
(chart/table cards) into one shape:
- `columns[QueryColumn]` — `column`, `aggregation?` (`SUM`\|`AVG`\|…), `alias?`, `format?`
- `group_by[]` — attribute columns (→ TS row/x axis)
- `order_by[]` — `{column, order: ASCENDING|DESCENDING}` (→ TS sort)
- `filters[QueryFilter]` — `{column, operand, values[]}` (`operand` e.g. `LAST_90_DAYS`,
  `GREATER_THAN`, `IN`)
- `limit?`, `offset?`, `distinct?`

**`Page`** — `id`, `name`, `card_ids[]` (str, resolve to `Card.urn`), `collection_ids[]`
(→ Liveboard tabs when populated), `children[]` (subpages), `owners[]`, `visibility{}`.

**`ExtractionNote`** — `object_type`, `object_id`, `severity`
(`info`\|`warning`\|`needs_review`), `message`. Every gap the extractor hits is recorded here
rather than guessed, and surfaces in the migration report.

## Cross-reference invariants (the parser must resolve, in order)

1. `Page.card_ids[i]` → `Card.urn` (a page's cards). Resolve **first** — drives Liveboard layout.
2. `Card.data_set_id` → `Dataset.id` (a card's model).
3. `BeastMode.data_source_id` → `Dataset.id`; a Beast Mode may also be duplicated inside a
   card's `calculated_fields[]` by name — dedupe by `(data_set_id, name)`.
4. Joins are **not** carried by Domo (the schema API has no relations). Infer by shared column
   name across datasets (`Customer ID`) or take from `overrides.json`; always flag inferred joins
   `needs_review` in the report.
