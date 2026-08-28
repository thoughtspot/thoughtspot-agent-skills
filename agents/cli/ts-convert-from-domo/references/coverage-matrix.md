<!-- coverage-matrix last-reviewed: 2026-08-26 -->
# Coverage matrix — Domo → ThoughtSpot

Every Domo construct and its conversion status. Cite in the migration report. Within
Mapped: **Migrated** (faithful/deterministic) · **Approximated** (mapped with a caveat,
verify). Anything a human must resolve is **NEEDS REVIEW** and is listed under Unmapped
Constructs. Source of truth for the formula rows is
`tools/ts-cli/ts_cli/domo/functions.py` (`FUNCTION_MAP` / `PASSTHROUGH_MAP` /
`_UNSUPPORTED_RE`).

## Mapped Constructs

### Objects

| Construct | ThoughtSpot target | Status | Notes |
|---|---|---|---|
| Dataset (`schema.columns`) | Table TML | Migrated | type map: STRING/DATETIME/DOUBLE/LONG |
| Dataset-to-dataset join (no ETL) | Model join | NEEDS REVIEW | **inferred by shared column name** — Domo carries no relationship metadata. One join per dataset pair on an id-like key; a pair sharing only incidental columns is left unjoined and reported. Emitted `NEEDS REVIEW` in `mapping.json` — confirm cardinality |
| Magic ETL join graph (`--etl`) | Model joins | NEEDS REVIEW | `MergeJoin` keys + type → model joins (preferred over inference). Table names are reconciled against the bundle's datasets; unmatched joins are dropped and reported. `relationshipType` is honoured where ThoughtSpot can express it — a Domo **many-to-many** cannot be: it **is** emitted `MANY_TO_ONE` so the Model still builds, **and** the join's own report row carries a warning that measures fan out until a bridge table exists |
| Beast Mode (global) | Model formula | Migrated | deterministic subset only; window/LOD → NEEDS REVIEW |
| Card-local `calculatedFields` | Model formula | Migrated | deduped against global Beast Modes by `(dataset, name)` |
| Card `kpi` | Answer (KPI/headline) | Migrated | from `summaryNumber` |
| Card `column` / `line` / `pie` / `area` / `scatter` | Answer (matching chart type) | Migrated | mapped by `_CHART_MAP`; axes are attributes→x, measures→y |
| Card `bar` | Answer (BAR) | Migrated | from `chartBody` |
| Card `table` | Answer (TABLE) | Migrated | from `chartBody` |
| Page | Liveboard | Migrated | **only the first page** — later pages and their cards are reported `Skipped` (see Unmapped) |
| Card layout (`preferredFullWidth`/`preferredFullHeight`) | Liveboard tile size | Approximated | grid approximation |

### Card query constructs

| Construct | ThoughtSpot target | Status | Notes |
|---|---|---|---|
| `groupBy[]` | attribute columns (rows / x-axis) | Migrated | |
| `columns[].aggregation` = `SUM` | measure aggregation | Migrated | matches the Model default for numeric columns |
| `limit` | Answer row limit (`top N`) | Migrated | not applied to KPI cards |
| `chartType` `kpi` / `bar` / `table` | Answer `display_mode` + `chart.type` | Migrated | |

Everything else a card carries — sort, filters, quick filters, number formats,
conditional formatting — is **not** emitted. See Unmapped Constructs.

### Filter operands

None. Card `filters[].operand` values are parsed into the IR but no filter is emitted
onto the Answer or Liveboard — see Unmapped Constructs.

### Beast Mode formulas

See [../../../shared/mappings/domo/beastmode-thoughtspot-formula-translation.md](../../../shared/mappings/domo/beastmode-thoughtspot-formula-translation.md)
for the full function/aggregation table.

| Construct | ThoughtSpot target | Status | Notes |
|---|---|---|---|
| Arithmetic, comparison, logical operators | same operators | Migrated | |
| `SUM` / `AVG` / `MIN` / `MAX` / `COUNT` / `COUNT DISTINCT` | `sum` / `average` / `min` / `max` / `count` / `unique count` | Migrated | |
| `DATEDIFF(a, b)` (2-arg) | `diff_days(a, b)` | Approximated | day grain assumed; verify argument order — Domo may return b−a |
| `DATEDIFF(grain, a, b)` (3-arg) | — | NEEDS REVIEW | the grain argument is **kept**, producing a 3-arg call to a 2-arg function, so it is flagged and comment-wrapped rather than emitted. Every `diff_days` call in the expression is checked, not just the first |
| `STDDEV` / `VARIANCE` | `stddev` / `variance` | Approximated | verify sample vs population |
| `CONCAT` / `LENGTH` / `SUBSTRING` / `LEFT` / `RIGHT` / `INSTR` | `concat` / `strlen` / `substr` / `left` / `right` / `strpos` | Migrated | note `substr`, **not** `substring` |
| `UPPER` / `LOWER` / `TRIM` / `LTRIM` / `RTRIM` / `REPLACE` | `sql_string_op` pass-through | Migrated | these six do **not** exist as ThoughtSpot functions (BL-170/BL-171) — a bare call is rejected at import (error_code 14516), so they are translated to a warehouse-evaluated `sql_string_op` via the shared `formula_common.wrap_passthrough_calls` |

## Unmapped Constructs

Emitted as a flagged placeholder or skipped entirely — never silently downgraded to a
wrong-but-valid substitute. Each appears as `NEEDS REVIEW` in `mapping.json` and the
migration report.

| Construct | Why unmapped | Notes |
|---|---|---|
| Card **analyzer query** (which measure/dimension/aggregation a card plots) | No Domo API a token can reach exposes it, and it is absent from the offline card JSON for some card versions | The dominant fidelity limit. Supply the dashboard PDF to read chart/axes by hand; otherwise cards degrade to title + chart-type placeholders |
| Live (`domo-cloud`) fetch | Not wired into `parse_app` — `ts_cli/domo/client.py` is a probed foundation only (datasets, pages, card metadata, Beast Modes) | Offline bundle is the only supported input today. Tracked in `open-items.md` |
| Card `chartType` outside the mapped set (`kpi`/`bar`/`table`/`column`/`line`/`pie`/`area`/`scatter`) | Not in `_CHART_MAP` | Answer emitted in TABLE_MODE and flagged `NEEDS REVIEW` |
| `chartVersion` | **Not read at all** | The parser does not branch on it, so a non-2.0 card is parsed with 2.0 assumptions and whatever fails to read is flagged by the field-level notes rather than by a version check |
| Window / running-total / LOD Beast Modes (`OVER`, `PARTITION BY`, `RANK`, `LAG`/`LEAD`) | No deterministic ThoughtSpot equivalent via string translation | Formula emitted verbatim and flagged |
| `CASE WHEN … END` — single- **and** multi-branch | The token translator cannot faithfully restructure control flow | Emitted verbatim and flagged. Recommended rewrite (`if (c) then x else y`) is in the Beast Mode mapping reference |
| `IFNULL` / `COALESCE` / `NULLIF` / `CAST` | Need a structural rewrite, not a token swap | Emitted verbatim and flagged; recommended rewrites in the mapping reference |
| `MEDIAN` / `PERCENTILE` | No clean ThoughtSpot TML keyword | Emitted verbatim and flagged |
| Card `orderBy[]` (sort) | Not emitted onto the Answer | Parsed into the IR, then dropped — reported per card as `Approximated` with the sort spelled out |
| Card `filters[]` — incl. `IN`, `NOT_IN`, `BETWEEN`, `LAST_N_DAYS`, `THIS_MONTH`, `YTD`, `dateRangeFilter` | No filter is emitted onto the Answer or Liveboard | Parsed into the IR, then dropped — reported per card. **The Answer will show unfiltered, all-time data** |
| Card `quickFilters[]` | Not emitted as a Liveboard filter chip | Parsed into the IR, then dropped — reported per card |
| Card `conditionalFormats[]` | Not emitted | Parsed into the IR, then dropped — reported per card |
| Page `collectionIds` / `children` → Liveboard tabs | No `tabs` node is emitted — the Liveboard is a single page of tiles | `answers.py` emits `layout.tiles` only |
| Domo pages 2..n | Only the first page becomes a Liveboard | Each later page and every card on it is reported `Skipped` with the page named |
| Card `columns[].alias` (the tile's display label) | No label override is emitted | An Answer's `answer_columns` must name Model columns, so a card-local label cannot be carried without model-level aliasing. The Answer shows the underlying column name. Note Domo's `orderBy` references the **alias**, which is why the dropped-sort note quotes it as such |
| Beast Mode `status` other than `VALID` | Not translated as valid | Domo already marks the Beast Mode broken; it is emitted `NEEDS REVIEW` with the Domo status quoted rather than shipped as though it worked |
| Dataset / card `description` | Not emitted into TML | No `description` is written on the Table, Model or Answer |
| Beast Mode `global` flag | Not used | Global and card-local Beast Modes are treated identically (deduped by dataset + name) |
| Card `columns[].aggregation` other than `SUM` (`MIN`/`MAX`/`AVG`/`COUNT`) | No aggregation is emitted onto the Answer | The Answer falls back to the Model default (SUM for numerics), so a `MIN(Price)` card would read as `SUM(Price)`. Reported per card as `Approximated` |
| Domo column `format` (CURRENCY / NUMBER / percent / precision) | No number format is emitted | Parsed into the IR, then dropped — reported per card |
| Card drill paths and card-to-card links | No ThoughtSpot equivalent modelled yet | Deferred |
| Multi-page Domo apps | One page → one Liveboard today | Deferred |
