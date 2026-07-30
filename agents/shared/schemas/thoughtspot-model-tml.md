<!-- currency: thoughtspot — 2026-07 (2026-07-30: live-verified on se-thoughtspot — columns[].description confirmed on formula-backed entries, no data_type on formulas[]/columns[], and the single join-type vocabulary INNER/LEFT_OUTER/RIGHT_OUTER/OUTER confirmed in both Model and Table contexts; earlier 2026-07-30: added columns[] properties.calendar / index_priority / is_attribution_dimension, widened index_type + currency_type from a product-docs sweep; also 2026-07-30, from a 500-document TML property census on se-thoughtspot covering 143 Models: added action_object_associations[] and columns[].properties.value_casing, extended geo_config with the country boolean and custom-map roles, rewrote the calendar value vocabulary, recorded index_priority as a non-integral number, loosened the joins[] either/or framing for 12 observed hybrids, and raised the lesson_plans evidence to 8 Models; prior: validated in 2026-07-11 external sweep) -->

# ThoughtSpot Model TML — Construction Reference

How to construct a valid ThoughtSpot Model TML for import via the REST API or
stored procedures. Platform-agnostic — applies to any source (Snowflake, Databricks,
Redshift, standalone model creation, etc.).

For Table TML construction, see [thoughtspot-table-tml.md](thoughtspot-table-tml.md).
For parsing exported TML, see [thoughtspot-tml.md](thoughtspot-tml.md).

> Hard rules every Model-producing conversion skill must obey: see [ts-model-conversion-invariants.md](./ts-model-conversion-invariants.md).

---

## Full Model TML Structure

```yaml
guid: "{existing_guid}"        # document root — omit on first import; required to update in-place
model:
  name: MODEL_NAME
  description: "Optional description"
  model_tables:
  - name: FACT_TABLE            # exact ThoughtSpot table object name
    fqn: "{table_guid}"         # GUID of the ThoughtSpot table object
    joins:                      # inline joins — only on the FROM (source) table entry
    - with: DIM_TABLE           # must equal the `name:` of the target entry (case-sensitive)
      'on': '[FACT_TABLE::FK_COL] = [DIM_TABLE::PK_COL]'
      type: INNER
      cardinality: MANY_TO_ONE
  - name: DIM_TABLE
    fqn: "{dim_guid}"
    referencing_join: "join_name_from_table_tml"   # Scenario A only — see below
  # Same physical table used twice: give each entry a different alias
  # - name: LOT_DRUGS
  #   alias: LOT_DRUGS_1
  #   fqn: "{guid}"
  # - name: LOT_DRUGS
  #   alias: LOT_DRUGS_2
  #   fqn: "{guid}"
  columns:
  - name: "Display Name"
    column_id: FACT_TABLE::COL_NAME   # TABLE_NAME::col_name — table name (or alias) from model_tables
    properties:
      column_type: ATTRIBUTE    # ATTRIBUTE or MEASURE
  - name: "Revenue"
    column_id: FACT_TABLE::AMOUNT
    properties:
      column_type: MEASURE
      aggregation: SUM
      format_pattern: "#,##0"   # optional display format
      currency_type:
        iso_code: USD           # optional — adds currency symbol
  - name: "FK Column"
    column_id: FACT_TABLE::CUSTOMER_ID
    properties:
      column_type: ATTRIBUTE
  - name: "Order Count"
    formula_id: formula_Order Count   # references a formulas[] entry by its id
    properties:
      column_type: MEASURE
      aggregation: COUNT
      index_type: DONT_INDEX
  formulas:
  - id: formula_Order Count         # id format: "formula_" + name (spaces preserved)
    name: "Order Count"
    expr: "count ( [FACT_TABLE::ORDER_ID] )"
  properties:
    is_bypass_rls: false
    join_progressive: true
    spotter_config:
      is_spotter_enabled: true
```

---

## Field Reference

### Top-level fields

| Field | Required | Notes |
|---|---|---|
| `guid` | On update only | Document root — NOT inside `model:`. Omit on first import. |
| `obj_id` | No | Document root — ThoughtSpot-assigned content ID (e.g. `DunderMifflinSales-0e4406c7`). Appears after export; do not set manually on import. To change it, use the "Change Object ID" option in the ThoughtSpot UI. |
| `model.name` | Yes | Display name in ThoughtSpot |
| `model.description` | No | Optional description |
| `model.model_tables` | Yes | One entry per physical ThoughtSpot table |
| `model.columns` | Yes | One entry per visible column/formula in the model |
| `model.formulas` | No | Formula definitions — each must have a matching `columns[]` entry |
| `model.parameters` | No | Runtime input parameters — referenced in formula `expr` as `[Param Name]` |
| `model.filters` | No | Model-level pre-filters applied before any query |
| `model.joins_with` | No | Data augmentation joins at the model level (e.g. joining an uploaded CSV to the model) |
| `model.properties` | No | Model-level settings |
| `model.lesson_plans` | No | In-product guided-lesson strings attached to the model — a list of `{lesson_id: <int>, lesson_plan_string: <string>}` entries, a sibling of `properties:` rather than a key inside it. **Shape confirmed 2026-07-30** against 8 real Models on `se-thoughtspot` (a 143-Model census; `lesson_id` is 0-based) (e.g. `{lesson_id: 0, lesson_plan_string: "What were [Sales] by [Store Region] in [Date].'last year' ?"}`). Pass through on round-trips; do not emit when generating a model. |

### `model_tables[]` fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Exact ThoughtSpot table object name — case-sensitive, copy verbatim |
| `alias` | No | When the same physical table appears more than once (e.g. self-join or two roles for one dim), assign a unique alias per entry. `column_id` then uses the alias as the table prefix: `LOT_DRUGS_1::MOLECULE`. |
| `fqn` | Yes on first import | GUID of the ThoughtSpot table object. For repoint operations, prefer `obj_id` over `fqn` when supported (avoids VERSION_CONFLICT 14009). Use one or the other on each entry, not both. |
| `obj_id` | No | ThoughtSpot-assigned content ID (format: `{NAME}-{first_8_chars_of_guid}`, e.g. `DM_ORDER-924f10e2`). Only present when exported with `export_options.include_obj_id_ref: true`. Preferred over `fqn` for repoint operations — avoids VERSION_CONFLICT (error 14009) on some builds. When importing with `obj_id`, omit `fqn` on the same entry (and vice versa). |
| `id` | No | When present, must equal `name` exactly (same case). ThoughtSpot uses `name` as the join reference target when `id` is absent. Omitting `id` is simpler. |
| `joins` | No | Joins FROM this table — lives on the source (FK) table entry only. Each entry is usually either a **referencing join** (Scenario A: `with` + `referencing_join`) or an **inline join** (Scenario B: `with` + `on` + `type` + `cardinality`) — but the two are **not strictly exclusive**: real joins carry `referencing_join` *plus* an inline attribute. See Join Scenarios below, and *Hybrid joins* under `joins[]` fields. |

### `joins[]` fields (on `model_tables` FK entry)

Each `joins[]` entry has `with` (always required) plus **one of two forms**:

**Scenario A — referencing a pre-defined Table TML join:**

| Field | Required | Notes |
|---|---|---|
| `with` | Yes | Must equal the `name:` of the target `model_tables[]` entry exactly (case-sensitive) |
| `referencing_join` | Yes | Name of a `joins_with[]` entry in the source Table TML. System-inferred joins have auto-generated names like `SYS_CONSTRAINT_<uuid>`. |

**Scenario B — inline join (no pre-defined Table TML join):**

| Field | Required | Notes |
|---|---|---|
| `with` | Yes | Must equal the `name:` of the target `model_tables[]` entry exactly (case-sensitive) |
| `on` | Yes | Quote with `'on':` — `on` is a YAML reserved word. Format: `[FROM::fk] = [TO::pk]`. Supports range/inequality operators — see Range Joins below. |
| `type` | Yes | `INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, or `OUTER`. **`OUTER` *is* the full outer join** — it is ThoughtSpot's name for it, not a narrower join type (per ThoughtSpot domain review, 2026-07-30). `FULL_OUTER` is **not** a ThoughtSpot value and is rejected: "Invalid value FULL_OUTER … Allowed values are INNER, LEFT_OUTER, OUTER, RIGHT_OUTER". So mapping a source `FULL OUTER` to `OUTER` is a **rename, not a downgrade** — no semantics are lost. Table `joins_with[].type` accepts exactly the same four and rejects `FULL_OUTER` identically (both live-probed — see the note below); SQL View `joins[].type` is documented with the same four but was **not** probed, so treat it as strongly inferred rather than verified. |
| `cardinality` | Yes | `MANY_TO_ONE` for most fact-to-dimension joins. Census-observed vocabulary across 233 real inline joins: `MANY_TO_ONE` ×223, `ONE_TO_MANY` ×11, `ONE_TO_ONE` ×3 — **`MANY_TO_MANY` never**. |

**Hybrid joins — the two scenarios are not strictly exclusive (2026-07-30 census).** Across 493
real `joins[]` entries in 143 Models:

| Key set | Count | |
|---|--:|---|
| `with` + `referencing_join` | 248 | pure Scenario A |
| `with` + `on` + `type` + `cardinality` | 233 | pure Scenario B |
| `with` + `referencing_join` + `type` | **8** | **hybrid** |
| `with` + `referencing_join` + `cardinality` | **4** | **hybrid** |

So 12 of 493 joins carry a `referencing_join` **and** an inline attribute — e.g.
`{with: Dim_Promotion, referencing_join: "Promotion_Key - Promotion_Key", type: LEFT_OUTER}`
(`Retail Sales` and two copies of it) and
`{with: CUST_PROFILING_ALL, referencing_join: "…", cardinality: MANY_TO_ONE}`
(`Demo Bank Deposits`, ×4).

**Consequence for a parser:** branching strictly on "has `referencing_join` ⇒ ignore
`type`/`cardinality`" silently drops a join attribute on those 12. Read the inline attributes
whenever they are present, regardless of `referencing_join`. When **generating**, still pick one
form — emitting both is not necessary and the precedence between them is unverified.

**Non-equality joins: zero observed.** No inline join in the 143-Model census contains `>=`, `<=`,
`>` or `<` in its `on` expression. The range / ASOF support documented below is correct per
ThoughtSpot's docs but is **entirely unexercised on that cluster** — no live evidence either way.

**Join-type vocabulary — re-verified 2026-07-30 on `se-thoughtspot`.** The `FULL_OUTER`
rejection recorded here from an earlier real import failure is **still current** on this
build, and the probe extended it in two ways:

| Context probed | `FULL_OUTER` | `OUTER` / `INNER` / `LEFT_OUTER` / `RIGHT_OUTER` |
|---|---|---|
| Model inline `model_tables[].joins[].type` | rejected — error 14528 | all accepted |
| Table `joins_with[].type` | **also rejected** — error 14528, identical allowed list | all accepted |

Verbatim response for the Table context (the newly-corrected half) — the whole `status`
object, so the `error_code` is on the record and not just asserted:

```json
{"status": {"error_message": "Invalid value <b> FULL_OUTER </b> of field <b> table->joins_with(1st)->type </b>. Allowed values are <b> INNER, LEFT_OUTER, OUTER, RIGHT_OUTER </b>. <br/><br/>G7PROBE_JOIN: Skipped relationship import as source_table is not populated, possible because import of source table failed. <br/>", "status_code": "ERROR", "error_code": 14528}}
```

(The trailing "Skipped relationship import" sentence is a cascade of the `type` failure — it
is absent from all five passing probes on the same document.)

So `OUTER` is the full outer join and `FULL_OUTER` is valid in **neither** probed context.
ThoughtSpot's own TML documentation extends this to Views, giving
`type: [RIGHT_OUTER | LEFT_OUTER | INNER | OUTER]` for Models, Views and Worksheets alike —
note that the **SQL View context was not probed**, so its vocabulary is documented and
inferred from these two siblings rather than directly verified.
`FULL_OUTER` was previously documented as valid for Table `joins_with[]` in
[thoughtspot-table-tml.md](thoughtspot-table-tml.md) and
[thoughtspot-sql-view-tml.md](thoughtspot-sql-view-tml.md); that was wrong and is corrected.

#### Range / Inequality Joins

The `on` expression supports `>=`, `>`, `<`, `<=` operators and `and` to combine
multiple conditions. This enables range joins (half-open interval), ASOF joins
(temporal point-in-time), and other inequality-based relationships.

**Range join** — half-open interval (`>=` start, `<` end):

```yaml
joins:
- with: DATE_TZ_BRIDGE
  'on': '[EVENTS::EVENT_TS] >= [DATE_TZ_BRIDGE::UTC_START_TS] and [EVENTS::EVENT_TS] < [DATE_TZ_BRIDGE::UTC_END_TS]'
  type: LEFT_OUTER
  cardinality: MANY_TO_ONE
```

Common use case: timezone bridge tables, SCD Type 2 effective-date ranges, rate
tables with valid-from/valid-to windows.

**ASOF join** — most recent matching row (`>=` on a temporal column):

```yaml
joins:
- with: RATES
  'on': '[TRADES::SYMBOL] = [RATES::SYMBOL] and [TRADES::TRADE_TS] >= [RATES::RATE_TS]'
  type: LEFT_OUTER
  cardinality: MANY_TO_ONE
```

**Notes:**
- Use `LEFT_OUTER` — if the range has no match, the fact row is preserved with
  NULLs for the target columns (same semantics as SQL `LEFT JOIN`)
- ThoughtSpot normalises the `on` expression on export (wraps sub-expressions in
  parentheses and uppercases `AND`)
- The same operators work in Table TML `joins_with[].on` expressions

### `columns[]` fields

| Field | One of | Notes |
|---|---|---|
| `column_id` | Physical column | Format: `TABLE_NAME::col_name` — TABLE_NAME is the `name:` (or `alias:`) from model_tables |
| `formula_id` | Formula reference | Must match a `formulas[].id` exactly (case-sensitive, spaces included) |
| `name` | Yes (always) | Display name shown in ThoughtSpot search bar |
| `description` | No | Free-text column description, a **sibling of `name`** (not under `properties:`). Valid on **both** `column_id` and `formula_id` entries — a formula-backed column's description lives here, because the `formulas[]` entry has no `description` field of its own. Live-verified 2026-07-30 on `se-thoughtspot`, and corroborated the same day at 7× the sample by a 143-Model property census: **63 of 549** formula-backed columns carry one, and **1,960 of 4,436** physical columns do (72 of 143 Models have at least one) — it is the second-most-common optional `columns[]` key on the cluster. ThoughtSpot's own Model TML syntax lists `description: <optional_column_description>` as a `columns[]` key. Pass through on round-trips. |
| `properties.column_type` | Yes | `ATTRIBUTE` or `MEASURE` |
| `properties.aggregation` | No | For MEASURE: `SUM`, `COUNT`, `AVERAGE`, `MIN`, `MAX`, `COUNT_DISTINCT`. The full documented set also includes `NONE`, `STD_DEVIATION` and `VARIANCE` — accept all nine when round-tripping an exported model, and prefer the six above when generating one. Valid on both `column_id` and `formula_id` entries. **Warning:** `COUNT_DISTINCT` on a `column_id` causes ThoughtSpot to silently override `column_type` to `ATTRIBUTE`. Always use a `formulas[]` entry with `unique count ( [TABLE::col] )` instead. |
| `properties.index_type` | No | `DONT_INDEX` suppresses text-search indexing. `PREFIX_ONLY` indexes only the string prefix (faster prefix search on long strings). The full documented set also includes `DEFAULT`, `PREFIX_AND_SUBSTRING` and `PREFIX_AND_WORD_SUBSTRING` — accept all five when round-tripping an exported model. Omit for full indexing (default). |
| `properties.index_priority` | No | A **number** — raises or lowers this column's priority in search indexing relative to others. **Emitted non-integrally (2026-07-30 census):** every one of the 20 observed sightings is `10.0`, `9.0`, `8.0`, `7.0` or `2.0`, confirmed verbatim in the raw `edoc` string (`"index_priority":10.0`) and not an artefact of JSON parsing. A strict *integer* validator therefore rejects real ThoughtSpot output — parse it as a number and accept a `.0` fraction. Pass through on round-trips. |
| `properties.is_attribution_dimension` | No | Boolean — marks the column as an attribution dimension. Pass through on round-trips. |
| `properties.is_hidden` | No | `true` hides the column from the search bar. **Do not set during conversion or model creation** — hidden columns cause locked visualizations and unexpected query behaviour. Leave visibility decisions to the model owner after import. |
| `properties.is_additive` | No | `true` marks a column as additive — used on semi-additive models to explicitly allow summation across time. |
| `properties.format_pattern` | No | Number display format string. Common values: `"#,##0"` (integer), `"#,##0.0%"` (percentage), `"###0"` (plain). |
| `properties.currency_type` | No | Adds currency symbol and formatting to a measure. Exactly **one** of three mutually-exclusive forms: `iso_code: USD` (a fixed ISO code — the common case), `column: <column_name>` (the code is read per row from another column), or `is_browser: true` (format in the viewer's browser locale). Only `iso_code` is used when generating new models; accept all three when round-tripping. |
| `properties.geo_config` | No | Geographic role for the column. See Geo Config below. |
| `properties.spotiq_preference` | No | `"EXCLUDE"` removes the column from SpotIQ auto-analysis (use on lat/long, internal IDs). |
| `properties.search_iq_preferred` | No | `true` flags this column as preferred in Search IQ / natural language queries. |
| `properties.ai_context` | No | Free-text description used by Spotter (AI search) to understand the column's business meaning. Appears on most columns in AI-enriched models. Pass through on round-trips; safe to omit when constructing new models. |
| `properties.custom_order` | No | Array of attribute values in custom display order. Used to control sort order in visualizations (e.g. `[USA, UK, France]`). ATTRIBUTE columns only. |
| `properties.default_date_bucket` | No | Default time granularity for date columns. Values: `DAILY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`, `YEARLY`, `AUTO`. Omit for ThoughtSpot default. |
| `properties.calendar` | No | **Date columns only** — the custom / fiscal calendar the column is bucketed by, so quarters and years follow a fiscal or 4-4-5 retail calendar instead of the Gregorian one. **Reference only:** the calendar itself is a *Connection-scoped* object created outside TML (`POST /api/rest/2.0/calendars/create`, 10.12.0.cl or later, backed by a warehouse calendar table), so this value is meaningless on a target instance whose connection has no calendar of that name. **Do not emit when generating a model** — pass through on round-trips only. **Value vocabulary — settled 2026-07-30** by a 500-document census, superseding the "not settled" note this row previously carried: the value is a **calendar name**, and the literal `calendar` is the default spelling. See the sub-table below. |
| `properties.value_casing` | No | Documented as a Table-column refinement, but **present on Model columns too — 545 sightings across 18 of 143 Models** (2026-07-30 census), including 156 on *formula-backed* columns. Same vocabulary as the Table reference (`UPPER` / `LOWER` / `MIXED` / `UNKNOWN`); every observed Model value is `UNKNOWN`. Pass through on round-trips; do not emit when generating a model. |
| `properties.synonyms` | No | Array of alternative names for search. **Must live under `properties:`** — top-level `synonyms:` at the column root is silently dropped on import. |
| `properties.synonym_type` | No | `USER_DEFINED` for user-supplied synonyms; `AUTO_GENERATED` for ThoughtSpot-inferred. Set to `USER_DEFINED` whenever you populate `properties.synonyms`. |
| `data_panel_column_groups` | No | Assigns the column to one or more data panel folders. Map of `{folder_name: ''}` — values are always empty string. A column can appear in multiple folders. Folder names must match entries in `column_groups[].column_group_info[].name`. Pass through on round-trips. |

#### `properties.calendar` — observed values (census, 2026-07-30)

500 documents across all four TML types, 143 of them Models:

| Value | Occurrences | Where | Reading |
|---|--:|---|---|
| `calendar` (the literal string) | 70 | 34 unrelated Models — `TST_*`, `PUB_*`, `VER_*`, `Retail Sales - RLS`, `Transaction History`, `Inventory Planning`, `Care Provider`, `Mobile Network Analysis`, … — almost always on a column named `Full Date` or `Month Start Date` | **The default spelling.** Neither our references nor ThoughtSpot's docs previously recorded it |
| `SeanTSCROOTS` | 1 Model + 1 **Table** | `454 Cal Test (Sean)` col `Transaction Date`; `FACT_RETAPP_SALES` col `RECORDDATE` | A real custom-calendar **object name** |
| `Dupont_Fiscal_Cal` | 1 | `Test Custom Calendars` col `Eff Start Date` | A real custom-calendar object name |
| `CALENDAR_TYPE_GREGORIAN` | **0** | — | **Not emitted by this build, on any document type.** [thoughtspot-sql-view-tml.md](thoughtspot-sql-view-tml.md) records this literal; it is now marked unverified there — including on the SQL Views where that file claims it (0 of 40) |
| `default` | **0** | — | Not emitted either, despite appearing in ThoughtSpot's published `[ default \| calendar_name ]` |

Three consequences:

1. **Emit and read a calendar *name*.** ThoughtSpot's published `calendar_name` form is right; the
   `CALENDAR_TYPE_GREGORIAN` enum spelling is wrong or at least not current.
2. **`calendar:` is honoured on a Table column**, not only a Model column — see
   [thoughtspot-table-tml.md](thoughtspot-table-tml.md). It also appears on **formula-backed**
   Model columns (5 sightings), which neither reference previously contemplated.
3. **Still open:** whether the literal `calendar` is a genuine default sentinel or a customer
   calendar that happens to be named "calendar". The 34-Model spread across unrelated tenants
   strongly favours *sentinel*, but confirming it needs a `GET /api/rest/2.0/calendars/…` read.

### `formulas[]` fields

| Field | Required | Notes |
|---|---|---|
| `id` | Recommended | Referenced by `columns[].formula_id`. Format: `formula_` + name (spaces preserved). |
| `name` | Yes | Display name |
| `expr` | Yes | ThoughtSpot formula expression. Use `>-` block scalar if expression contains `{ }` curly braces. |
| `properties.column_type` | No | `ATTRIBUTE` or `MEASURE`. Optional in the `formulas[]` entry itself. |
| `was_auto_generated` | No | `true` when ThoughtSpot auto-generated this formula (e.g. AI-derived). `false` or absent = user-created. Pass through on round-trips; never set to `true` when constructing new formulas. |

**A `formulas[]` entry has no `description` and no declared data type** (verified 2026-07-30 on
`se-thoughtspot` against a 40-model sample and ThoughtSpot's published Model TML syntax). Put a
formula's description on the surfacing `columns[]` entry instead — that is its home. There is no
`data_type` key on either the `formulas[]` or the `columns[]` entry: ThoughtSpot derives a
formula's type from its expression, and it cannot be declared. Note that acceptance is not
evidence here — a Model import silently ignores unknown keys on a `columns[]` entry, so an
invented `data_type:` validates clean and does nothing.

**Never add `aggregation:` to a `formulas[]` entry** — formulas are self-contained through
their `expr`. Adding `aggregation:` causes `FORMULA is not a valid aggregation type`.
Add `aggregation:` to the corresponding `columns[]` entry instead.

**`aggregation:` on a formula `columns[]` entry — whether it applies depends on whether the
`expr` is scalar or already aggregated.** *Per ThoughtSpot domain review, 2026-07-30* — the
earlier blanket claim ("ignored at query time", stated universally) was wrong:

| `expr` shape | Example | Does `columns[].properties.aggregation` apply? |
|---|---|---|
| **Scalar** (row-level, no aggregate function) | `[FACT::AMOUNT] - [FACT::COST]` | **Yes.** The formula behaves like a fact column: it is evaluated per row and then rolled up by the column's declared `aggregation`. This is the same model as a physical fact column with a default aggregation (Snowflake's FACT + default aggregation is the direct analogy). |
| **Aggregate** (the `expr` already contains an aggregate) | `sum ( [FACT::AMOUNT] - [FACT::COST] )` | **No — it is a no-op.** ThoughtSpot evaluates the aggregate in the `expr`; the column-level `aggregation` does not re-aggregate the result. |

Two consequences for generators:

- A **scalar** MEASURE formula needs its `aggregation:` chosen deliberately — it is load-bearing.
  `SUM` is the right default for an additive quantity, but a scalar ratio or rate must not carry
  `SUM`, because the sum of per-row ratios is not the ratio of the sums.
- An **aggregate** MEASURE formula may carry `aggregation: SUM` as a harmless convention; it has
  no query-time effect either way. Do not attempt to infer a "correct" aggregation from the
  expression shape in this case — there is nothing to get right.

Both patterns are legitimate and idiomatic. The scalar form is the more reusable of the two: the
formula stays at row grain, so it can be re-aggregated differently in different searches, and it
composes into other formulas.

> **Evidence class.** This is a **query-time semantic**, so `VALIDATE_ONLY` import probing cannot
> test it — both shapes import clean with any `aggregation:` value (the aggregate form was
> confirmed to validate on `se-thoughtspot`, 2026-07-30). The scalar-versus-aggregate distinction
> above rests on ThoughtSpot domain review, not on an import probe, and closing it empirically
> would need a query-result comparison against live data.

**Formula cross-references: reference by id, not display name.** The two reference styles
behave differently on import, and only one fails:

- **Display-name ref** (`[Other Formula Name]`) **fails on first import** with "Search did not
  find 'other formula name'" — ThoughtSpot parses the bare name as search tokens, and the
  referenced formula is not resolvable as a reference during import validation.
- **Id-ref** (`[formula_<Name>]`) **resolves on first import and is order-independent** — a
  formula may be declared before the one it references. So all formulas can go in a **single
  import pass** (one model TML, formulas emitted with `formula_`-prefixed refs); no two-pass or
  phasing is required for cross-reference resolution. Verified on ps-internal 2026-07-09
  (id-refs resolved both ordered and forward; display-name refs failed identically either way).

**Workaround (only if you must keep a display-name ref, e.g. legacy):** inline the referenced
formula's full expression, or use a two-pass import (import base formulas first, export to get
GUIDs, then add dependent formulas via update).

### Geo Config

Assign a geographic role so ThoughtSpot can render map charts:

```yaml
# Latitude
properties:
  geo_config:
    latitude: true
  spotiq_preference: "EXCLUDE"   # exclude raw lat/long from auto-analysis

# Longitude
properties:
  geo_config:
    longitude: true
  spotiq_preference: "EXCLUDE"

# Named region (state, zip, county, city, country)
properties:
  geo_config:
    region_name:             # a DICT, not a list — census-confirmed on Models AND Views
      country: "UNITED STATES"
      region_name: "state"   # state | zip code | county | city | country

# Country role — a BARE BOOLEAN, and distinct from region_name.country (a string)
properties:
  geo_config:
    country: true

# Custom-map role — points at an uploaded custom map file
properties:
  geo_config:
    custom_file_guid: "f3faaa74-147f-4376-ac42-eff0c3779f6f"
    geometryType: POLYGON    # POLYGON | MULTI_POLYGON
```

**Five geo roles exist, not three (2026-07-30 census).** Observed distribution across 143 Models:

| Role shape | Occ | Docs | Note |
|---|--:|--:|---|
| `region_name: {country, region_name}` | 88 | 39 | The common case. A **dict** — [thoughtspot-view-tml.md](thoughtspot-view-tml.md) and [thoughtspot-sql-view-tml.md](thoughtspot-sql-view-tml.md) previously documented a list; both corrected the same day |
| `latitude: true` | 17 | 17 | |
| `longitude: true` | 17 | 17 | |
| `custom_file_guid` + `geometryType` | 7 | 3 | **Custom maps exist in production.** `geometryType` ∈ {`POLYGON`, `MULTI_POLYGON`} |
| `country: true` | 5 | 5 | **A fifth role this reference did not document.** A bare boolean — do not confuse it with `region_name.country`, which is a *string* naming the country a region belongs to |

**`custom_file_guid` is instance-local.** It names an uploaded custom-map file by GUID, so a
portable document must not carry it — the geo role has to be dropped rather than translated. Pass
through only on a same-instance round trip. `geo_config` also appears on **formula-backed** columns
(2 sightings), which this reference did not previously contemplate.

### `properties` fields

| Field | Default | Notes |
|---|---|---|
| `is_bypass_rls` | false | Set true to bypass row-level security. **Always emitted on export** — 143 of 143 census Models carry it, every one `false` |
| `join_progressive` | true | ThoughtSpot execution hint — always set true. Always emitted (143/143; `true` ×142, `false` ×1) |
| `spotter_config.is_spotter_enabled` | true | Enables Spotter (AI search) for this model. Always emitted (143/143; `true` ×128, `false` ×15) |

### `action_object_associations[]`

A model-level construct, **undocumented until 2026-07-30** and found by the census (1 of 143
Models — `MT Retail Sales`). It binds a **custom action** to the Model, so the action appears in
the relevant menu when a user is working with data from it.

```yaml
model:
  name: MODEL_NAME
  action_object_associations:
  - action_name: "Generate Forecast"   # display name of an existing custom action
    context: CONTEXT_MENU              # only value observed
    enabled: true
```

| Field | Type | Observed values |
|---|---|---|
| `action_name` | string | `Generate Forecast` — names a custom action object that exists outside TML |
| `context` | string | `CONTEXT_MENU` (the only value seen; the product also exposes primary/menu placements, so treat the vocabulary as open) |
| `enabled` | bool | `true` |

**Treat it as a presentation binding, not semantics.** The action itself is a separate object that
this document only references by display name, so the association is meaningless on an instance
without an action of that name — the same reasoning as `properties.calendar`. **Do not emit when
generating a model**; pass through on round-trips only, and note that a round trip to an instance
lacking the action is a silent no-op rather than an error. It is a sibling of `properties:`, not a
key inside it.

### `parameters[]` fields

Runtime input parameters that users can set at query time. Referenced in `formulas[].expr` using bracket notation: `[Parameter Name]` (same syntax as a column reference but with no `TABLE::` prefix).

| Field | Notes |
|---|---|
| `id` | UUID assigned by ThoughtSpot. Omit on first import; ThoughtSpot assigns it. |
| `name` | Display name — referenced in formulas as `[Parameter Name]` |
| `data_type` | `INT64`, `DOUBLE`, `CHAR`, `DATE`, `BOOL`. **Use `CHAR` for string-typed list parameters** — `VARCHAR` is accepted by the schema but fails on import for list parameters. |
| `default_value` | Always a string in TML regardless of `data_type` |
| `description` | Optional description |
| `list_config` | Restricts values to a fixed list. Contains `list_choice[]` — **each entry must be an object** with `value` (required) and `display_name` (recommended). Bare string values are rejected. |
| `range_config` | Restricts values to a numeric range. Contains `range_min`, `range_max`, `include_min`, `include_max`. |

Only one of `list_config` or `range_config` may be present. Omit both for a free-form parameter.

```yaml
parameters:
# Free-form numeric parameter
- id: "4aa0677f-b1e6-40c2-a33e-7da656820710"
  name: FTE Hourly Rate
  data_type: INT64
  default_value: "40"
  description: ""

# List parameter (user picks from fixed choices)
- id: "7fec5e34-7d01-4ba7-ac1a-6803b57bd6dd"
  name: Date
  data_type: CHAR
  default_value: ship date
  list_config:
    list_choice:
    - value: order date
      display_name: order date
    - value: ship date
      display_name: ship date
  description: ""

# Date parameter (free-form date input)
- id: "a3a83826-7fc5-46bd-b1b6-fc2d71c26dfc"
  name: End Date
  data_type: DATE
  default_value: 12/31/2024
  description: ""

# Boolean list parameter
- id: "65ed55ca-d66f-4205-b547-bc495bb6fb9f"
  name: Master Date Filter
  data_type: BOOL
  default_value: 'false'
  list_config:
    list_choice:
    - value: 'true'
    - value: 'false'
  description: ""
```

Parameter references in formula expressions: `[FTE Hourly Rate]` — no `TABLE::` separator. ThoughtSpot resolves these at query time. Parameters with no `TABLE::` prefix are untranslatable to Snowflake Semantic View SQL (no runtime parameter equivalent).

### `filters[]` fields

Model-level pre-filters applied before any query. Column references use display name (not `column_id`).

| Field | Required | Notes |
|---|---|---|
| `column` | Yes | List of column display names the filter applies to |
| `oper` | No | Comparison operator — see values below |
| `values` | No | Filter values as strings. Date values use `MM/DD/YYYY` format. |
| `display_name` | No | Human-readable label for the filter. Pass through on round-trips. |
| `is_single_value` | No | `true` restricts the filter to a single value. Default false. |
| `apply_on_tables` | No | List of table aliases (from `model_tables[]`) this filter applies to. **Absent → filter is always applied (mandatory).** Present → filter only applies when one of the listed tables is included in the search. |

Valid `oper` values: `=`, `!=`, `>`, `>=`, `<`, `<=`, `between`, `in`, `not_in`

```yaml
filters:
# Value filter
- column:
  - "Query Stats Is System"   # display name of the column to filter on
  oper: in
  values:
  - "false"

# Numeric comparison
- column:
  - Quantity
  oper: '>'
  values:
  - '100'

# Date comparison — date values as MM/DD/YYYY strings
- column:
  - ship date
  oper: '>='
  values:
  - 04/08/2026

# Range filter
- column:
  - "Order Date"
  oper: between
  values:
  - "01/01/2000"
  - "03/01/2025"

# Formula-backed boolean filter
- column:
  - "wsFilter"               # formula column name (boolean expression)
  oper: in
  values:
  - "true"

# Table-scoped filter — only applies when Lineorder or Supplier is in the search
- column:
  - Region
  oper: in
  values:
  - APAC
  apply_on_tables:
  - Lineorder
  - Supplier
```

### `column_groups[]`

Defines the data panel folder structure shown in the ThoughtSpot search bar. Each column is assigned to one or more folders via `data_panel_column_groups` on the column entry.

| Field | Notes |
|---|---|
| `type` | `DATA_PANEL` — the only observed value. Controls the search bar data panel grouping. |
| `properties.status` | `ENABLE` to show the grouped panel; `DISABLE` to hide it. |
| `properties.default_sort` | `ENABLE` sorts columns within each folder alphabetically by default. |
| `column_group_info[].name` | Folder display name. Must match keys used in `data_panel_column_groups` on columns. |
| `column_group_info[].include_ungrouped_columns` | `true` on exactly one entry (the catch-all folder) — columns with no `data_panel_column_groups` entry appear there. |

```yaml
column_groups:
- type: DATA_PANEL
  properties:
    status: ENABLE
    default_sort: ENABLE
  column_group_info:
  - name: Dates
    include_ungrouped_columns: false
  - name: Measures
    include_ungrouped_columns: false
  - name: Products
    include_ungrouped_columns: false
  - name: Customers
    include_ungrouped_columns: false
  - name: Orders
    include_ungrouped_columns: false
  - name: Ungrouped      # catch-all — columns with no data_panel_column_groups appear here
    include_ungrouped_columns: true
```

Assigning columns to folders — on each column entry:
```yaml
- name: Amount
  column_id: DM_ORDER_DETAIL::LINE_TOTAL
  properties:
    column_type: MEASURE
    aggregation: SUM
  data_panel_column_groups: {Measures: ''}   # single folder

- name: State
  column_id: DM_CUSTOMER::STATE
  properties:
    column_type: ATTRIBUTE
  data_panel_column_groups: {Products: '', Customers: ''}  # two folders — map values always ''
```

Pass through `column_groups` and `data_panel_column_groups` on round-trips. Do not construct from scratch unless the user explicitly wants folder organisation.

---

### `joins_with[]` at model level

Data augmentation joins — used to join an uploaded CSV or external dataset directly to the model. Distinct from `model_tables[].joins[]`. Includes an `is_one_to_one` flag.

```yaml
joins_with:
- name: "ModelName_to_UploadedDataset"
  destination:
    name: "Demo set - Department Budgets"
    fqn: "{table_guid}"
  'on': "[ModelName::department] = [Demo set - Department Budgets::Department]"
  type: LEFT_OUTER
  is_one_to_one: true
```

---

## `constraints`

Rolling date window constraints applied at query time. Distinct from `filters[]` — constraints define a dynamic "last N periods" window rather than a static value predicate. Used primarily for performance: they limit how far back ThoughtSpot scans on large fact tables.

The outer key is `constraints:`, which contains a single `constraint:` list (not a list at the top level).

`date_range_condition` fields:

| Field | Notes |
|---|---|
| `column` | Display name of the date column (not `TABLE::col` format) |
| `duration` | Integer number of time periods (e.g. `1` = last 1 year) |
| `bucket` | Time granularity: `DAY`, `WEEK`, `MONTH`, `QUARTER`, `YEAR` |

**Single table — one date column:**
```yaml
constraints:
  constraint:
  - table: DM_ORDER_DETAIL
    condition:
    - date_range_condition:
        column: date
        duration: 1
        bucket: YEAR
```

**Multi-fact — each fact table independently windowed:**
```yaml
constraints:
  constraint:
  - table: sales
    condition:
    - date_range_condition:
        column: date
        duration: 1
        bucket: YEAR
  - table: inventory
    condition:
    - date_range_condition:
        column: date
        duration: 1
        bucket: YEAR
```

**AND — same table, different date columns (both conditions must be met):**
```yaml
# Repeating table entries for the same table = AND logic
constraints:
  constraint:
  - table: sales
    condition:
    - date_range_condition:
        column: ship date
        duration: 1
        bucket: YEAR
  - table: sales
    condition:
    - date_range_condition:
        column: order date
        duration: 1
        bucket: YEAR
```

**OR — multiple conditions within one table entry (either condition met):**
```yaml
# Multiple date_range_condition entries within one condition: list = OR logic
constraints:
  constraint:
  - table: sales
    condition:
    - date_range_condition:
        column: ship date
        duration: 1
        bucket: YEAR
    - date_range_condition:
        column: order date
        duration: 1
        bucket: YEAR
```

Pass through `constraints` on round-trips. Do not add constraints when constructing new models unless the user explicitly requests a rolling date window.

---

## `aggregated_models`

Associates pre-aggregated "aggregate models" with this base model for query switching. ThoughtSpot evaluates these at query time — when a query matches the aggregation level of an aggregate model, it automatically routes to that model instead of the base model (a performance optimization).

```yaml
aggregated_models:
- id: "{aggregate_model_guid}"
  date_aggregation_info:
  - column_id: order date    # display name of the date column
    bucket: MONTHLY          # DAY | WEEK | MONTH | QUARTER | YEAR
```

**Always pass through `aggregated_models` on round-trips.** Stripping this field silently removes the query routing optimisation — ThoughtSpot falls back to the base model for all queries with no error.

Do not construct `aggregated_models` from scratch; aggregate model associations are managed in the ThoughtSpot UI.

---

## GUID and Updates

**`guid` at document root — never inside `model:`:**

```yaml
guid: "{existing_model_guid}"   # MUST be first key in the document
model:
  name: MODEL_NAME
  # ...
```

`guid` nested under `model:` (e.g. `model: { guid: ... }`) is **silently ignored** —
ThoughtSpot creates a new duplicate object with the same name. This is the most common
cause of "update creates a new model" failures.

**First import:** omit `guid`. After import, record the GUID from the response.

**Finding an existing GUID:**
```bash
ts metadata search --subtype WORKSHEET --name '%{model_name}%' --profile {profile}
```

**Deleting a duplicate:**
```bash
ts metadata delete {wrong_guid} --profile {profile}
```

### Import policy: `PARTIAL` for multi-model batches

When importing multiple models in a single call, use `--policy PARTIAL` instead of
`--policy ALL_OR_NONE`. With `ALL_OR_NONE`, if **any** TML in the batch fails, the
entire batch is rolled back — including models that parsed and imported successfully.
The import response still returns `status_code: OK` with GUIDs for those models, but
the objects are not persisted. This is a silent data loss: the caller sees success
GUIDs but the objects don't exist.

`PARTIAL` allows each TML to succeed or fail independently. Failed models are reported
in the response; successful models are persisted.

Use `ALL_OR_NONE` only when the batch is a single atomic unit (e.g., one table + one
model that references it) where partial success would leave broken references.

```bash
# Multi-model batch — use PARTIAL
echo '["{model1_tml}", "{model2_tml}"]' | ts tml import --policy PARTIAL --profile {profile}

# Single model or atomic table+model pair — ALL_OR_NONE is safe
echo '["{table_tml}", "{model_tml}"]' | ts tml import --policy ALL_OR_NONE --profile {profile}
```

Verified 2026-05-28: 12-model batch with 6 failures silently rolled back all 12
despite 6 returning success GUIDs.

---

## Join Scenarios

### Scenario A — Pre-defined joins (Table TML has `joins_with`)

Use when the ThoughtSpot Table objects already have `joins_with` entries defined.
The model references these joins by name via `referencing_join` inside a `joins:`
array on the **FK (FROM) table entry** — not as a standalone field on the dim entry:

```yaml
model_tables:
- name: FACT_TABLE        # FK side — joins array goes here
  fqn: "{fact_guid}"
  joins:
  - with: DIM_TABLE       # target table's name:
    referencing_join: "FACT_TABLE_to_DIM_TABLE"  # name from Table TML's joins_with[]
- name: DIM_TABLE         # PK side — no joins array
  fqn: "{dim_guid}"
```

To find the join name: export the FROM table's TML → find `joins_with[]` → match entry
where `destination.name` equals the TO table name → use that entry's `name` value.

### Scenario B — Inline joins (no pre-defined joins, or new table objects)

Use when Table objects have no `joins_with`, or when tables were just created and
have no pre-defined joins. The `joins:` array lives on the source (FK) table entry:

```yaml
model_tables:
- name: FACT_TABLE        # FK side — joins array goes here
  fqn: "{fact_guid}"
  joins:
  - with: DIM_TABLE       # target table's name:
    'on': '[FACT_TABLE::FK_COL] = [DIM_TABLE::PK_COL]'
    type: INNER
    cardinality: MANY_TO_ONE
- name: DIM_TABLE         # PK side — no joins array
  fqn: "{dim_guid}"
```

**`joins:` at model top level causes "destination is missing" error.** Always nest
inside the source table's `model_tables[]` entry.

---

## Formula Visibility

**Every formula must appear in `columns[]`** via `formula_id:` — formulas defined in
`formulas[]` but not referenced in `columns[]` are not surfaced in the model.

```yaml
formulas:
- id: formula_Revenue            # step 1: define the formula
  name: "Revenue"
  expr: "sum ( [DM_ORDER_DETAIL::LINE_TOTAL] )"

- id: formula_Inventory Balance
  name: "Inventory Balance"
  expr: >-                        # >- required when expr contains { } curly braces
    last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )

columns:
- name: "Revenue"                 # step 2: surface it as a column
  formula_id: formula_Revenue
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX

- name: "Inventory Balance"
  formula_id: formula_Inventory Balance
  properties:
    column_type: MEASURE
    aggregation: SUM
    index_type: DONT_INDEX
```

`formula_id` must match the formula's `id` exactly — case-sensitive, spaces included.

---

## `column_id` Construction

Format: `TABLE_NAME::col_name`

- `TABLE_NAME` is the `name:` value from the corresponding `model_tables[]` entry
- `col_name` is the column's `name` from the **ThoughtSpot Table TML** (which may differ
  from the physical warehouse column name if the table was created with a display name)

Always export and read the Table TML to get authoritative column names — never guess
from the warehouse schema alone.

---

## Self-Validation Checklist

Run before every import. Fix all issues silently before showing the user.

| # | Check | What to verify |
|---|---|---|
| 1 | YAML validity | Parse the TML string; no syntax errors |
| 2 | `model_tables[].name` | Every name is the exact ThoughtSpot table object name (case-sensitive) |
| 3 | `referencing_join` values | Every value matches a join name from the exported Table TML |
| 4 | `column_id` table prefix | Each prefix (before `::`) matches a `name:` or `alias:` in `model_tables[]` |
| 5 | `column_id` column suffix | Each suffix (after `::`) matches a column name in the ThoughtSpot Table TML |
| 6 | No duplicate `column_id` | No two `columns[]` entries share the same `column_id` |
| 7 | No `aggregation:` on formulas | No `formulas[]` entry has an `aggregation:` field |
| 8 | No duplicate display names | Every `name` across `columns[]` and `formulas[]` is unique |
| 9 | `column_type` placement | Where present on columns, `column_type` is under `properties:` — not bare |
| 10 | Every formula in `columns[]` | Every `formulas[].id` has a matching `formula_id:` in `columns[]` |
| 11 | `last_value` YAML encoding | Any formula `expr` containing `{ }` uses `>-` block scalar |
| 12 | `guid` placement | If updating, `guid` is at document root — not inside `model:` |

---

## Common Import Errors

| Error | Cause | Fix |
|---|---|---|
| `duplicate column_id` | Same `column_id` in two `columns[]` entries | Convert the COUNT_DISTINCT duplicate to a formula: `unique count ( [TABLE::col] )` |
| MEASURE silently becomes ATTRIBUTE | `aggregation: COUNT_DISTINCT` on a `column_id` (physical column) | TS overrides `column_type` to ATTRIBUTE on physical refs. Use a formula: `unique count ( [TABLE::col] )` |
| `referencing_join not found` | Join name wrong or join doesn't exist at the Table object level | Re-export the Table TML and verify the join name |
| `column_id not found` | Wrong column name suffix | Export Table TML and use the exact `name` from `table.columns[]` |
| `destination is missing` | `joins:` placed at model top level instead of inside a `model_tables[]` entry | Move joins inside the FROM table's entry |
| `{table_name} does not exist in schema` | `with:` value doesn't match any `name:` in `model_tables[]` | Copy the target table's `name:` verbatim |
| `Compulsory Field … joins(N)->with is not populated` | Missing `with:` field on a join | Add `with: {target_name}` to every join |
| `No enum constant ColumnTypeEnum` | `column_type:` is bare (not under `properties:`) | Nest: `properties: column_type: ATTRIBUTE` |
| `FORMULA is not a valid aggregation type` | `aggregation:` set on a `formulas[]` entry | Remove `aggregation:` from formulas — put it on the `columns[]` entry instead |
| `duplicate column name {name}` | Two columns/formulas share the same display `name` | FK columns often duplicate PK column names — prefix: "Order Customer Id" vs "Customer Id" |
| `Multiple tables have same alias` | Two `model_tables[]` entries share the same `name` with no `alias` | Add distinct `alias:` values when the same table appears more than once |
| `fqn resolution failed` | GUID is stale or from a different instance | Re-retrieve the GUID for the table |
| YAML mapping error on formula | Formula `expr` with `{ }` written as inline string | Use `>-` block scalar for the `expr` value |
| YAML parse error | Non-printable characters in strings | Strip non-printable chars before serialising |
