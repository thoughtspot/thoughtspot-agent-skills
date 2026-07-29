# ThoughtSpot TML ↔ Ossie construct mapping

**Status:** draft for review on apache/ossie#285 · **Ossie spec version:** `0.2.0.dev0`
(`core-spec/spec.yaml:20`, `core-spec/spec.md:24`; all Ossie citations below are
`path:line` against apache/ossie @ `c26b61c`) · **TS ground truth:**
`agents/shared/schemas/thoughtspot-model-tml.md` and
`agents/shared/schemas/thoughtspot-table-tml.md` — internal paths in the ThoughtSpot
skills repo, cited below by section name as the *Model TML reference* and the
*Table TML reference*. They are the authoritative record of ThoughtSpot's TML shape
(derived from real import failures) and override any other description of it.

This document proposes the construct-level mapping for a bidirectional ThoughtSpot
converter. The companion expression/function mapping — one row per
`core-spec/expression_language.md` function and operator — is a separate document;
this one stops at the boundary where an expression string begins.

---

## What ThoughtSpot's side of the mapping is

ThoughtSpot's semantic layer is expressed in **TML** (ThoughtSpot Modeling Language):
YAML documents, one per object, distinguished by their root key.

| TML document | Root key | Role |
|---|---|---|
| **Model** | `model:` | The semantic model. Declares which tables participate (`model_tables[]`), the joins between them, which columns and formulas the model exposes (`columns[]`, `formulas[]`), and model-scope settings. |
| **Table** | `table:` | One warehouse table registered in ThoughtSpot: `db` / `schema` / `db_table`, the named warehouse `connection`, and the physical `columns[]` with their types. |
| **SQL View** | `sql_view:` | Same role as Table, but backed by a `sql_query` instead of a physical table. Columns live in `sql_view_columns[]`, each bound to a query output alias via `sql_output_column`. |

Two consequences shape everything below:

1. **One Ossie semantic model corresponds to 1 + N TML documents** — one `model:`
   document plus one `table:`/`sql_view:` document per dataset. A converter reads and
   writes the *set*, not a single file. The Model references each Table by name plus an
   instance-local identifier.
2. **Formulas are model-scope, not dataset-scope.** ThoughtSpot computed columns live in
   the Model document's `formulas[]`, not on the table. Ossie `fields` are *inside* a
   dataset, so every computed field needs an attribution decision (see Field level).

A ThoughtSpot **Worksheet** (root key `worksheet:`, columns in `worksheet_columns[]`) is
the predecessor of the Model and is deliberately out of scope — see non-mapping **NM6**.

## Direction naming and fidelity vocabulary

Directions are always written out: **`TML → Ossie`** (converter entry point
`tml_to_ossie`) and **`Ossie → TML`** (`ossie_to_tml`).

| Fidelity | Meaning |
|---|---|
| `lossless` | Both sides have a native field; the value survives unchanged. |
| `via custom_extensions` | One side has no field for it; the value is carried in the `custom_extensions` entry with `vendor_name: THOUGHTSPOT` and restored on the return trip. |
| `lossy→issue` | The receiving side cannot represent it at all. The converter emits a structured issue naming the object and the dropped construct. Never a silent drop. |
| `mixed` | A **container** row whose fidelity is not one value, because the row expands into a level of its own: the per-key verdicts live in that level's table, and the Notes cell names which one to read. Used on `relationships` and `metrics` (Semantic model level) and `fields` (Dataset level) — nowhere else. |
| `see there` | Fidelity is stated by a **rule** elsewhere in this document rather than by a table row. Used for `expression.dialects[]`, whose verdict is per-function: the rule is *Expression handling*, and the per-function verdicts are in the companion function-mapping document. |

All three base tokens are also written in a **qualified form** — `lossless (structure)`,
`lossless (equi-join)`, `lossy→issue (formula)`, `via custom_extensions (multi-dataset)` — and
often as a pair. The parenthetical names the *case* the verdict holds for, and two conventions
combine them:

- **`/` means the fidelity splits by case.** `lossless (equi-join) / lossy→issue (non-equi)`
  reads as "lossless for an equi-join, `lossy→issue` for a non-equality one" — exactly one side
  applies to any given input.
- **`+` means both apply to the same case.** `lossy→issue + via custom_extensions
  (multi-dataset)` reads as "for the multi-dataset case, an issue is raised *and* the construct
  is stashed" — the loss is reported and the value is still preserved.

A qualified `lossless` is therefore never a weaker `lossless`; it is a `lossless` with its
domain stated, and every row that qualifies one also states what happens outside that domain.

### The stash is asymmetric — and that matters for what "lossless" can mean

`custom_extensions` is an *Ossie* construct (`core-spec/spec.md:420-430`). TML has no
vendor-extension field of any kind. So:

- **`TML → Ossie → TML` is the round trip the stash makes lossless** — except for the
  explicit non-mappings **NM1**–**NM6**, which are deliberately not carried in either
  direction (instance-local identifiers, RLS rules, presentation and coaching objects,
  aggregate associations, legacy object types). Every other ThoughtSpot-only concept is
  serialised on the way out and restored on the way back.
- **`Ossie → TML → Ossie` is lossy for every Ossie construct TML cannot express**, and no
  stash can fix it — there is nowhere in TML to put it. Each such loss is reported as an
  issue; the rows below mark them `lossy→issue`, and the datatype table names the
  collapses explicitly.

`data` is a JSON **string**, not a nested object: `osi-schema.json:73-76` types it
`"string"` and `osi-schema.json:66-80` sets `additionalProperties: false` on the
extension object, so a nested payload is a schema-validation failure rather than a style
choice (`core-spec/spec.md:426-430` says the same). Two rules follow: the payload schema
below describes the *content of that string*, and any round-trip comparison must
`json.loads()` both sides before comparing — serialised key order and whitespace are not
stable.

## Identifiers — the second non-obvious thing

| Concern | Ossie | ThoughtSpot |
|---|---|---|
| Field identity | `field.name` — an ANSI SQL identifier, ≤128 chars, regular (unquoted) identifiers case-insensitive (`core-spec/expression_language.md:71-79`) | `columns[].name` — the **display name** shown in the search bar. May contain spaces and mixed case, and is *also* the reference key |
| Display label | `field.label` | no separate field — `name` is both |
| Physical column | inside `expression` | `db_column_name` on the Table column |
| Reference syntax inside expressions | `dataset.field`, dot-separated (`core-spec/expression_language.md:98`) | `[TABLE_NAME::Column Display Name]`, where `TABLE_NAME` is the `model_tables[]` `name` or `alias` |

Rules the converter follows in both directions:

- **ID1** `TML → Ossie` sets `field.name` to a normalised identifier derived from the
  ThoughtSpot display name and puts the exact display name in `field.label`
  (precedent: the Databricks converter maps `field.label` → `display_name`,
  `converters/databricks/README.md:89`). `Ossie → TML` uses `label` when present, else
  `name`.
- **ID2** Normalisation can collide — two distinct ThoughtSpot display names can fold onto
  one identifier (`Order Date` and `Order-Date` → `order_date`), and Ossie treats regular
  identifiers as case-insensitive for resolution
  (`core-spec/expression_language.md:77`), so a case-only difference is ambiguous even
  though `validation/validate.py:99-116` only rejects exact-string duplicates. Collisions
  are resolved with a numeric suffix; the exact original stays in `label` and in the stash.
- **ID3** Expression identifiers are **rewritten**, never passed through textually:
  `[TABLE::Column]` ↔ `dataset.field` in both directions.
- **ID4** ThoughtSpot requires display names to be unique across `columns[]` *and*
  `formulas[]` in one Model (Model TML reference, *Self-Validation Checklist* #8), which
  is a stricter constraint than Ossie's per-dataset field uniqueness: an Ossie document
  with `orders.status` and `customers.status` needs one of them renamed on the way in
  (the classic case is a foreign key sharing a name with the primary key it points at).

---

## Semantic model level

Ossie schema: `core-spec/spec.md:88-96`; required keys `name` and `datasets`
(`osi-schema.json:348`).

| Ossie | ThoughtSpot | Direction notes | Fidelity |
|---|---|---|---|
| `name` | `model.name` | Normalised per ID1; when normalisation changed it, the exact ThoughtSpot name is stashed as `tml_name` | lossless |
| `description` | `model.description` | | lossless |
| `ai_context` (string form, or its `instructions` key) | Model-scope Spotter instructions | ThoughtSpot's model-scope instruction surface is configured **outside** the Model TML document — the Model TML reference documents no field for it, and per-column `properties.ai_context` is the only in-TML AI-context surface. `TML → Ossie` has nothing to read; `Ossie → TML` cannot write it | lossy→issue |
| `ai_context.synonyms` | — | No model-scope synonym field in Model TML (`properties.synonyms` exists on columns only) | lossy→issue |
| `ai_context.examples` | — | Example questions exist in ThoughtSpot as separate objects with their own identity, not as Model fields — see **NM4** | lossy→issue |
| `datasets` | `model_tables[]` + one `table:`/`sql_view:` document per entry | 1 + N documents. The `model_tables[]` entry carries the join graph and the instance-local reference (`fqn`/`obj_id`), which is never round-tripped — see **NM1** | lossless (structure) |
| `relationships` | Table `joins_with[]` (referenced from the Model by name) or `model_tables[].joins[]` (inline) | See Relationship level | mixed |
| `metrics` | `formulas[]` + the `columns[]` entries that surface them (`formula_id`, `column_type: MEASURE`) | See Metric level | mixed |
| `custom_extensions` | The `THOUGHTSPOT` entry is the payload below; entries for other vendors are passed through untouched in both directions | Following `converters/README.md`'s own edge-case guidance (preserve unknown-vendor entries rather than discard them) | lossless / via custom_extensions |

Model-scope ThoughtSpot-only constructs — `properties` (`is_bypass_rls`,
`join_progressive`, `spotter_config.is_spotter_enabled`), `parameters[]`, `filters[]`,
`constraints`, `column_groups[]`, and model-level `joins_with[]` data-augmentation joins
— have no Ossie field and travel `via custom_extensions` (payload keys below).
`filters[]` and `constraints` are the semantically loudest of these: a stashed filter is
invisible to a non-ThoughtSpot consumer, so the same model can return different numbers
in two tools. That is upstream ask **A3**.

## Dataset level

Ossie schema: `core-spec/spec.md:124-133`; required keys `name` and `source`
(`osi-schema.json:225`).

| Ossie | ThoughtSpot | Direction notes | Fidelity |
|---|---|---|---|
| `name` | Table `table.name`, which must equal the `model_tables[]` `name` exactly (case-sensitive) | **One dataset per participating entry, not per physical table.** When one physical table participates twice (self-join, or one dimension in two roles) each `model_tables[]` entry carries a distinct `alias` and `column_id` prefixes use the alias (Model TML reference, *`model_tables[]` fields*). Each alias is its own Ossie dataset with the same `source`; `alias` and the underlying table name are stashed so the return trip rebuilds aliases instead of duplicate Table objects | lossless / via custom_extensions (alias) |
| `source` | `db` + `schema` + `db_table`, joined as `DB.SCHEMA.TABLE`; or, for a `sql_view:`, the `sql_query` string | Ossie explicitly allows `source` to be a query (`core-spec/spec.md:127`), so a `source` that is not a three-part identifier becomes a `sql_view:` document. The parts are stashed individually when any part contains a `.` and the dotted form would be ambiguous | lossless |
| (`source`'s warehouse binding) | Table `connection.name` | ThoughtSpot reaches the warehouse through a **named Connection object**; the Table TML reference requires `connection.name` (a display name, never a GUID, and `fqn:` inside a connection block must never appear). Ossie has no connection concept → stashed as `connection_name`. `Ossie → TML` cannot emit a valid Table document without one, so a hand-authored Ossie document with no stash requires the connection name as a converter argument; absent both, `lossy→issue` | via custom_extensions |
| `primary_key` | no key declaration exists in Table TML | `TML → Ossie`: derived — the ordered `to_columns` of relationships that target this dataset with a to-one cardinality are its key evidence; omitted when not derivable. `Ossie → TML`: a key that no relationship uses has nowhere to go. Upstream precedent binds the same pair to a join hint (`rely.at_most_one_match`, `converters/databricks/README.md:85`); TML has no equivalent hint. See ask **A7** | lossless (join-derived) / lossy→issue (unused keys) |
| `unique_keys` | no key declaration exists in Table TML | Never emitted `TML → Ossie` — nothing in TML distinguishes a unique key from a join target. Dropped with an issue on the way in | lossy→issue |
| `description` | Table `table.description` | Documented in the Table TML reference, *`columns[]` fields* (the `table.description` row) | lossless |
| `ai_context` | — | No table-scope synonym or instruction field in Table TML | lossy→issue |
| `fields` | Table `columns[]`, surfaced by the Model `columns[]` entries whose `column_id` prefix is this dataset, plus ATTRIBUTE `formulas[]` attributed to it | See Field level. Table columns the Model does not surface are not part of the semantic model, so they are not emitted as fields; they are stashed as `unsurfaced_columns` so the Table document can be regenerated exactly | mixed |
| `custom_extensions` | dataset-scope payload below | Foreign-vendor entries pass through | lossless / via custom_extensions |

## Relationship level

Ossie schema: `core-spec/spec.md:183-191`; required keys `name`, `from`, `to`,
`from_columns`, `to_columns` (`osi-schema.json:270`). Ossie models a relationship as a
foreign-key **equality** between two ordered column lists, oriented many (`from`) → one
(`to`). It has no join-type field and no cardinality field.

| Ossie | ThoughtSpot | Direction notes | Fidelity |
|---|---|---|---|
| `name` | Table `joins_with[].name` — the value a Model references as `referencing_join` | ThoughtSpot supports two join shapes: a Table-level join referenced by name from the Model, and an inline join defined in the Model. Inline joins have no name, so `TML → Ossie` derives `{FROM}_to_{TO}`; which shape the source used, and the original name, are stashed | lossless / via custom_extensions |
| `from` | the FK side — the `model_tables[]` entry that owns the `joins[]` array, or the Table that owns the `joins_with[]` entry | ThoughtSpot always places a join on the FK side, so `from` is structural rather than a separate field. A `joins:` array at Model top level is an error (`destination is missing`) | lossless |
| `to` | inline join `with:` / Table join `destination.name` | Must equal the target `model_tables[]` entry's `name` exactly, case-sensitive | lossless |
| `from_columns` / `to_columns` | parsed from the join condition: `[FROM::a] = [TO::x] and [FROM::b] = [TO::y]` → ordered pairs | Ossie requires equal-length, order-corresponding arrays (`core-spec/spec.md:195-198`). **The boundary is non-equality joins:** ThoughtSpot supports range and ASOF joins using `>=`, `>`, `<`, `<=` and mixed predicates (Model TML reference, *Range / Inequality Joins*) for timezone bridges, SCD-2 effective-date windows and point-in-time lookups. These cannot be expressed as FK column pairs — the relationship is not emitted, the whole condition string is stashed, and an issue is raised. See ask **A6** | lossless (equi-join) / lossy→issue (non-equi) |
| (join `type`) | `INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, `OUTER` on model inline joins; Table joins also accept `FULL_OUTER` | No Ossie field. Stashed per relationship; `Ossie → TML` defaults to `INNER` when no stash is present, which matches an FK-equality relationship's semantics. `FULL_OUTER` is rejected in model inline joins — ThoughtSpot's error names `INNER, LEFT_OUTER, OUTER, RIGHT_OUTER` — so it is emitted as `OUTER` there (Model TML reference, *`joins[]` fields*) | via custom_extensions |
| (cardinality) | `MANY_TO_ONE`, `ONE_TO_ONE`, `ONE_TO_MANY`, `MANY_TO_MANY` | Ossie encodes cardinality only through orientation. `MANY_TO_ONE` maps to `from`→`to` directly; `ONE_TO_MANY` inverts the orientation; `ONE_TO_ONE` and `MANY_TO_MANY` have no orientation encoding at all. The value is stashed in every case and restored verbatim. Upstream does the same derivation in reverse (`converters/databricks/README.md:84`). See ask **A4** | via custom_extensions |
| `ai_context` | — | No join-scope AI context in TML | lossy→issue |
| `custom_extensions` | relationship-scope payload below | | via custom_extensions |

## Field and metric level

### Fields

Ossie schema: `core-spec/spec.md:231-240`; required keys `name` and `expression`
(`osi-schema.json:173`).

| Ossie | ThoughtSpot | Direction notes | Fidelity |
|---|---|---|---|
| `name` | `columns[].name`, normalised per ID1 | The exact display name round-trips through `label` | lossless |
| `label` | `columns[].name` verbatim | Read as the human display label, matching `converters/databricks/README.md:89`. See ask **A5** | lossless |
| `expression` — a single bare identifier | Table `columns[].db_column_name`, surfaced by a Model `columns[]` entry with `column_id: TABLE::Name` and `column_type: ATTRIBUTE` | The identifier is the *physical* column; the display name comes from `label`/`name`. `db_column_name` is emitted unconditionally — see **R1** | lossless |
| `expression` — computed | Model `formulas[]` entry (`id: formula_<Name>`, `name`, `expr`) plus a `columns[]` entry referencing it by `formula_id` with `column_type: ATTRIBUTE` | ThoughtSpot formulas are model-scope, so a computed field must be **attributed** to a dataset: attribute it to the dataset all its column references resolve to. When they span two or more datasets there is no correct dataset, and the converter does not guess — it raises an issue and preserves the formula in the model-scope stash (`unattributed_formulas`). This mirrors upstream's refuse-to-guess rule for expressions on fanned-out datasets | lossless (single dataset) / lossy→issue + via custom_extensions (multi-dataset) |
| `expression.dialects[]` | one ThoughtSpot formula string | See Expression handling | see there |
| `dimension.is_time` (`is_time` is the `dimension` object's only key — `osi-schema.json:127-137`) | a `DATE` / `DATE_TIME` column, plus `properties.default_date_bucket` for its default grain | `TML → Ossie`: ThoughtSpot has no temporal-role flag, so the role is derived from the column type and `is_time` is emitted **only** when it differs from the type-derived default (`core-spec/spec.md:337`) — which, given a type-derived role, is never; the field is simply omitted and the default applies. `Ossie → TML`: a time role on a **non-temporal** type — a year as `Integer`, a quarter name as `String` (`core-spec/spec.md:341-348`) — has no TML flag to write and, per **X9**, nothing to stash → issue. `properties.default_date_bucket` is a ThoughtSpot-only grain default, stashed in `column_properties` | lossless (temporal types) / lossy→issue (role on a non-temporal type) |
| `description` | Table `columns[].description` | A formula-backed field has no documented description field on the Model `columns[]`/`formulas[]` entry. Nothing in TML holds it, so per **X9** it cannot be stashed either — `Ossie → TML` raises an issue | lossless (physical) / lossy→issue (formula) |
| `datatype` | Table `db_column_properties.data_type` | See Datatype map. A formula-backed field has no declared type in Model TML, so it is omitted `TML → Ossie` (`datatype` is optional) and raises an issue `Ossie → TML` | lossless (physical) / lossy→issue (formula) |
| `ai_context.synonyms` | `properties.synonyms` **plus** `properties.synonym_type: USER_DEFINED` | Both TML references warn that a `synonyms:` key at the column root is *silently dropped* on import — it must sit under `properties:`, and `synonym_type` must be set whenever synonyms are populated | lossless |
| `ai_context` string form / `instructions` | `properties.ai_context` | The Model TML reference documents `properties.ai_context` as the Spotter-facing context on a Model column | lossless |
| `ai_context.examples` | — | No per-column example store in TML — see **NM4** | lossy→issue |
| `custom_extensions` | field-scope payload below (`index_type`, `geo_config`, `value_casing`, …) | | via custom_extensions |

### Metrics

Ossie schema: `core-spec/spec.md:365-372`; required keys `name` and `expression`
(`osi-schema.json:301`). Ossie metrics are **model-scope and may span datasets**
(`core-spec/spec.md:361`, and the cross-dataset example at `:403-416`) — exactly the
scope of a ThoughtSpot Model formula, so this level maps cleanly in both directions.

| Ossie | ThoughtSpot | Direction notes | Fidelity |
|---|---|---|---|
| `name` | `formulas[].name`, matched by the surfacing `columns[].name`, with `formulas[].id` = `formula_<Name>` and `columns[].formula_id` matching that id exactly | A `formulas[]` entry with no `columns[]` entry referencing it is **not surfaced** in the model at all (Model TML reference, *Formula Visibility*). Metrics have no `label` field, so when ID1 normalisation changes the name the exact ThoughtSpot display name is stashed | lossless / via custom_extensions (exact name) |
| `expression` | `formulas[].expr` | Always emitted as a formula, never as a physical column plus an aggregation — three grounded reasons in **R4** | lossless (translatable) / lossy→issue (untranslatable) |
| (the aggregation function, which lives *inside* `expression` — Ossie has no separate `aggregation` field) | `columns[].properties.aggregation` on the surfacing column | `TML → Ossie`: a `columns[]` entry with `column_id` + `aggregation: SUM` becomes the metric `SUM(dataset.field)`. The enum maps `SUM`/`COUNT`/`AVERAGE`/`MIN`/`MAX`/`COUNT_DISTINCT` ↔ `SUM`/`COUNT`/`AVG`/`MIN`/`MAX`/`COUNT(DISTINCT …)`, against Ossie's required core aggregations (`core-spec/expression_language.md:153-163`). **`aggregation:` belongs in `columns[]` entries only — never in a `formulas[]` entry** (the Model TML reference records `FORMULA is not a valid aggregation type` as the resulting import error), and `aggregation` on a formula column is *ignored at query time*, so the aggregation must be inside `expr` | lossless |
| `description` | no documented description field on a Model `columns[]`/`formulas[]` entry | Nothing in TML holds it, so per **X9** it cannot be stashed — `Ossie → TML` raises an issue | lossy→issue |
| `datatype` | measures are untyped in Model TML | `TML → Ossie` emits it only when the metric is a bare aggregate over a typed physical column (`COUNT` and `COUNT(DISTINCT …)` → `Integer`; otherwise the column's mapped type); otherwise omitted. `Ossie → TML` has nowhere to write it (**X9**) → issue | lossless (bare aggregate) / lossy→issue (otherwise) |
| `ai_context.synonyms` | `properties.synonyms` + `synonym_type` on the surfacing column | | lossless |
| `ai_context` string form / `instructions` | `properties.ai_context` on the surfacing column | `examples` is unsupported — see **NM4** | lossless / lossy→issue (`examples`) |
| `custom_extensions` | metric-scope payload below (`format_pattern`, `currency_type`, `index_type`, `is_additive`, …) | | via custom_extensions |

---

## Datatype map

Ossie datatypes: `core-spec/spec.md:69-80` and `osi-schema.json:111-126` — a closed
10-value enum, optional on both Field and Metric. ThoughtSpot values are from the
Table TML reference, *Data Type Mapping*, which also records that ThoughtSpot **rejects
SQL type names**: `BIGINT` returns `DataType BIGINT does not match CDW DataType`.

| Ossie datatype | TML `data_type` (`Ossie → TML`) | Ossie datatype emitted (`TML → Ossie`) | Notes |
|---|---|---|---|
| `String` | `VARCHAR` | `VARCHAR` → `String` | Lossless both ways. `properties.value_casing` (`UPPER`/`LOWER`/`MIXED`/`UNKNOWN`) is a ThoughtSpot-only refinement on VARCHAR columns → stashed in `column_properties` |
| `Integer` | `INT64` | `INT64` → `Integer` | ThoughtSpot's integer type is `INT64` — never `BIGINT` or `INTEGER` |
| `Decimal` | `DOUBLE` | `DOUBLE` → `Decimal` | ThoughtSpot has a single approximate numeric type, so `Decimal` and `Float` **collapse** into it. `TML → Ossie → TML` is exact (`DOUBLE` → `Decimal` → `DOUBLE`); `Ossie → TML → Ossie` cannot distinguish the two, and per **X9** no stash can recover it → **declared loss**, reported as an issue when the input said `Float` |
| `Float` | `DOUBLE` (`FLOAT` on a BigQuery-backed connection) | `FLOAT` → `Float` | The Table TML reference distinguishes `DOUBLE` for Snowflake-style numerics from `FLOAT` for BigQuery. A `FLOAT` column round-trips exactly; a `DOUBLE` one comes back as `Decimal` (row above) |
| `Boolean` | `BOOLEAN` (`BOOL` on a Snowflake-backed connection) | `BOOL` / `BOOLEAN` → `Boolean` | Lossless. The Table TML reference gives `BOOLEAN` as the general value and `BOOL` as the Snowflake-specific one, so `BOOLEAN` is the default and `BOOL` is selected from the connection. Which spelling the connection uses is recorded in the field stash's `data_type` key so the return trip re-emits the same one |
| `Date` | `DATE` | `DATE` → `Date` | Lossless |
| `Time` | `VARCHAR`, or `DATE_TIME` when the underlying column is timestamp-backed | — never emitted | ThoughtSpot's documented `data_type` set (Table TML reference, *Data Type Mapping*) has no time-of-day type at all — the closest values are `DATE`, `DATE_TIME` and `VARCHAR`. Per **X9** the original cannot be stashed, so this is a **declared loss** reported at conversion time |
| `DateTime` | `DATE_TIME` | `DATE_TIME` → `DateTime` | Lossless |
| `DateTimeTz` | `DATE_TIME` | — (see `DateTime`) | ThoughtSpot has no offset-aware column type — display time zone is an instance/user setting, not a column property. `Ossie → TML → Ossie` collapses to `DateTime` → **declared loss**, reported at conversion time |
| `Opaque` | `VARCHAR` | — never emitted | Ossie's escape hatch for a type outside the portable vocabulary (`core-spec/spec.md:80`). The marker collapses to `String` on a return trip → **declared loss**, reported at conversion time. Any accompanying vendor refinement in a foreign-vendor extension passes through untouched (**X7**) |
| *(omitted)* | derived from the warehouse; `INT64` when a numeric column's precision is unknown, per the Table TML reference's guidance to prefer `INT64` and let ThoughtSpot report a mismatch | omitted | `datatype` is optional on both sides; omission is a legitimate value, not a gap |

**Reverse-direction rule:** every Table column carries `db_column_properties.data_type`.
ThoughtSpot raises `Compulsory Field table->columns->db_column_properties is not
populated` when the block is absent, so an Ossie field with no `datatype` still needs one
inferred rather than omitted.

## Expression handling (summary — detail in the companion function-mapping document)

1. **Reference rewriting** — `[TABLE::Column]` ↔ `dataset.field` (ID3). Never a textual
   passthrough in either direction.
2. **Dialect selection, `Ossie → TML`** — prefer a `THOUGHTSPOT` dialect entry, else
   `ANSI_SQL`, else the first dialect the function mapping can translate; if none is
   translatable, raise an issue rather than emit a guess. This mirrors the Databricks
   converter's `DATABRICKS` → `ANSI_SQL` preference
   (`converters/databricks/src/ossie_databricks/_common.py:221-236`).
3. **Dialect emission, `TML → Ossie`** — emit a `THOUGHTSPOT` entry (the verbatim
   ThoughtSpot formula) **and** an `ANSI_SQL` entry wherever the expression is portable.
   The converter holds both representations at translation time, and the second tier is
   what makes the document useful to a non-ThoughtSpot consumer.
4. **Blocker — upstream ask A1.** `THOUGHTSPOT` is not in the `Dialect` enum
   (`osi-schema.json:24-27`, a closed 7-value enum; `core-spec/spec.md:52-60`), so a
   `THOUGHTSPOT` dialect entry **fails schema validation today**. It also needs adding to
   `SKIP_SQL_VALIDATION` (`validation/validate.py:75`, currently
   `{MDX, TABLEAU, MAQL}`): a ThoughtSpot formula is not SQL — a documented formula shape
   is `last_value ( sum ( [T::c] ) , query_groups ( ) , { [D::date] } )`, and no sqlglot
   dialect parses `{ }` grouping — and an unlisted dialect falls through
   `DIALECT_MAP.get(dialect) → None` (`validation/validate.py:64-72`, `:160`) into a
   default-dialect parse and a hard validation error.
5. **Constructs Ossie excludes from expressions** (`core-spec/expression_language.md:124-135`)
   are compatible with ThoughtSpot's formula language, with one gap: `WHERE` is redirected
   to "the filter property", which the core schema does not define. ThoughtSpot's model
   `filters[]` and `constraints` therefore have no Ossie home (ask **A3**).
6. **Runtime parameters.** A ThoughtSpot formula may reference a model parameter as
   `[Parameter Name]` — no `TABLE::` prefix. There is no Ossie equivalent, so such an
   expression is emitted with a `THOUGHTSPOT` dialect entry only, the `parameters[]`
   definitions are stashed, and an issue records that the metric is not portable.

---

## `custom_extensions[THOUGHTSPOT]` payload schema

### Protocol

Mirrors the Databricks converter's stash
(`converters/databricks/src/ossie_databricks/_common.py:176-215`):

- **X1** One entry per object, `vendor_name: THOUGHTSPOT`. Merge into an existing entry;
  never append a second.
- **X2** `data` is a JSON string (`osi-schema.json:73-76`). Compare parsed, never raw.
- **X3** `_v` is an integer shape version, bumped when the payload shape changes. An
  unrecognised `_v` raises an issue rather than being partially read.
- **X4** Malformed JSON raises a converter error naming the object — never a bare
  `JSONDecodeError`.
- **X5** Restoration is **stash-if-present-else-derive**. A hand-authored Ossie document
  has no stash and must still convert; every stashed key therefore needs a derivation or
  a documented default.
- **X6** Write nothing when the payload would be empty, so a converted document stays
  clean where ThoughtSpot added nothing.
- **X7** Entries for other vendors pass through untouched in both directions.
- **X8 (identity)** The payload carries **no** `guid`, `obj_id`, or `fqn` under any key.
  These are instance-local (see **NM1**); a portable document must not contain them, and
  re-importing a stale one fails with `fqn resolution failed`.
- **X9 (the stash can only carry what TML contains)** Because `custom_extensions` lives in
  the *Ossie* document, the stash is written by `tml_to_ossie` and read by
  `ossie_to_tml` — so **every key below is derivable from a TML document**. There is
  deliberately no key whose purpose is to preserve an *Ossie-only* value across
  `Ossie → TML → Ossie`: TML has nowhere to hold it, so `tml_to_ossie` would have nothing
  to read and the key could never be populated. Those losses are reported as issues, not
  stashed. This is the practical consequence of the stash asymmetry described above, and
  it is the single easiest thing to get wrong when designing the payload.

### Draft JSON Schema for the parsed `data` object

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "custom_extensions[THOUGHTSPOT].data (parsed)",
  "description": "Validate a parsed payload against the $defs entry for the level of the Ossie object the extension is attached to. There is deliberately no top-level oneOf: the levels are open objects and a payload is not identifiable by shape alone — the attachment point is what selects the schema.",
  "$defs": {
    "Base": {
      "type": "object",
      "required": ["_v"],
      "properties": {
        "_v": { "type": "integer", "const": 1, "description": "Payload shape version — rule X3" }
      }
    },
    "SemanticModelLevel": {
      "allOf": [{ "$ref": "#/$defs/Base" }],
      "properties": {
        "tml_name": { "type": "string", "description": "Exact model.name when ID1 normalisation changed it" },
        "model_properties": {
          "type": "object",
          "properties": {
            "is_bypass_rls": { "type": "boolean" },
            "join_progressive": { "type": "boolean" },
            "spotter_config": {
              "type": "object",
              "properties": { "is_spotter_enabled": { "type": "boolean" } }
            }
          }
        },
        "parameters": {
          "type": "array",
          "description": "Verbatim model.parameters[] entries (name, data_type, default_value, description, list_config | range_config). No Ossie equivalent; formulas referencing them are not portable.",
          "items": { "type": "object" }
        },
        "filters": {
          "type": "array",
          "description": "Verbatim model.filters[] entries (column display names, oper, values, apply_on_tables, is_single_value). Semantically load-bearing — see ask A3.",
          "items": { "type": "object" }
        },
        "constraints": {
          "type": "object",
          "description": "Verbatim model.constraints block (rolling date-window conditions per table)."
        },
        "column_groups": {
          "type": "array",
          "description": "Verbatim model.column_groups[] — the search-bar data-panel folder structure.",
          "items": { "type": "object" }
        },
        "model_joins_with": {
          "type": "array",
          "description": "Verbatim model-level joins_with[] data-augmentation joins (e.g. an uploaded dataset joined to the model).",
          "items": { "type": "object" }
        },
        "unattributed_formulas": {
          "type": "array",
          "description": "Formulas whose column references span two or more datasets, so no single Ossie dataset can own them. Preserved verbatim; an issue is raised alongside.",
          "items": {
            "type": "object",
            "required": ["name", "expr"],
            "properties": {
              "name": { "type": "string" },
              "expr": { "type": "string" },
              "column_properties": { "type": "object" }
            }
          }
        }
      }
    },
    "DatasetLevel": {
      "allOf": [{ "$ref": "#/$defs/Base" }],
      "properties": {
        "connection_name": {
          "type": "string",
          "description": "ThoughtSpot Connection display name (case-sensitive, never a GUID). Required to emit a Table document; when absent it must be supplied by the caller."
        },
        "tml_name": { "type": "string", "description": "Exact table.name when normalisation changed it" },
        "alias": { "type": "string", "description": "model_tables[].alias when one physical table participates more than once" },
        "table_name": { "type": "string", "description": "The underlying table object name that `alias` aliases" },
        "tml_object": { "enum": ["table", "sql_view"] },
        "source_parts": {
          "type": "object",
          "description": "db / schema / db_table recorded individually when the dotted `source` form would be ambiguous.",
          "properties": {
            "db": { "type": "string" },
            "schema": { "type": "string" },
            "db_table": { "type": "string" }
          }
        },
        "sql_query": { "type": "string", "description": "sql_view.sql_query when tml_object is sql_view" },
        "sql_output_columns": {
          "type": "object",
          "description": "field name -> sql_output_column alias, for sql_view columns",
          "additionalProperties": { "type": "string" }
        },
        "table_properties": {
          "type": "object",
          "properties": {
            "spotter_config": {
              "type": "object",
              "properties": { "is_spotter_enabled": { "type": "boolean" } }
            }
          }
        },
        "unsurfaced_columns": {
          "type": "array",
          "description": "Verbatim Table columns[] entries that the Model does not surface. Not semantic model content, but required to regenerate the Table document exactly.",
          "items": { "type": "object" }
        }
      }
    },
    "RelationshipLevel": {
      "allOf": [{ "$ref": "#/$defs/Base" }],
      "properties": {
        "type": { "enum": ["INNER", "LEFT_OUTER", "RIGHT_OUTER", "OUTER", "FULL_OUTER"] },
        "cardinality": { "enum": ["MANY_TO_ONE", "ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_MANY"] },
        "join_shape": {
          "enum": ["referencing", "inline"],
          "description": "referencing = a named Table joins_with[] entry the Model points at; inline = defined in model_tables[].joins[]"
        },
        "referencing_join": { "type": "string", "description": "The Table joins_with[] name, when join_shape is referencing" },
        "on_expression": {
          "type": "string",
          "description": "The verbatim join condition. Required when the condition is not a pure equality (range / ASOF joins), where from_columns/to_columns cannot represent it."
        },
        "is_one_to_one": { "type": "boolean", "description": "Seen on data-augmentation and SQL-view joins" }
      }
    },
    "FieldLevel": {
      "allOf": [{ "$ref": "#/$defs/Base" }],
      "properties": {
        "column_properties": {
          "type": "object",
          "description": "ThoughtSpot column properties with no Ossie home.",
          "properties": {
            "index_type": { "enum": ["DONT_INDEX", "PREFIX_ONLY"] },
            "value_casing": { "enum": ["UPPER", "LOWER", "MIXED", "UNKNOWN"] },
            "default_date_bucket": { "enum": ["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY", "AUTO"] },
            "custom_order": { "type": "array", "items": { "type": "string" } },
            "geo_config": { "type": "object", "description": "latitude / longitude / region_name role for map rendering" },
            "spotiq_preference": { "type": "string" },
            "search_iq_preferred": { "type": "boolean" },
            "synonym_type": { "enum": ["USER_DEFINED", "AUTO_GENERATED"] },
            "is_hidden": { "type": "boolean", "description": "Preserved on round trip; never invented — see R8" },
            "is_additive": { "type": "boolean" },
            "format_pattern": { "type": "string" },
            "currency_type": { "type": "object", "properties": { "iso_code": { "type": "string" } } },
            "data_panel_column_groups": { "type": "object", "description": "Data-panel folder membership; map values are always the empty string" }
          }
        },
        "data_type": {
          "type": "string",
          "description": "The exact ThoughtSpot db_column_properties.data_type, recorded when it is not the canonical target of the mapped Ossie datatype (BOOLEAN rather than BOOL, FLOAT rather than DOUBLE), so the return trip re-emits the same spelling."
        },
        "formula": {
          "type": "object",
          "description": "Present when the field is formula-backed.",
          "properties": {
            "id": { "type": "string" },
            "expr": { "type": "string" },
            "was_auto_generated": { "type": "boolean" }
          }
        }
      }
    },
    "MetricLevel": {
      "allOf": [{ "$ref": "#/$defs/Base" }],
      "description": "No key exists here for `description` or `datatype`: neither has a Model-TML home, so per X9 there is nothing for tml_to_ossie to read and nothing to stash.",
      "properties": {
        "tml_name": { "type": "string", "description": "Exact display name when normalisation changed it (metrics have no `label`)" },
        "shape": {
          "enum": ["formula", "column_aggregation"],
          "description": "Which TML shape the source used, so TML -> Ossie -> TML reproduces it. New TML is always emitted as `formula` — see R4."
        },
        "column_id": { "type": "string", "description": "TABLE::Column, when shape is column_aggregation" },
        "column_properties": {
          "type": "object",
          "properties": {
            "aggregation": { "enum": ["SUM", "COUNT", "AVERAGE", "MIN", "MAX", "COUNT_DISTINCT"] },
            "index_type": { "enum": ["DONT_INDEX", "PREFIX_ONLY"] },
            "format_pattern": { "type": "string" },
            "currency_type": { "type": "object", "properties": { "iso_code": { "type": "string" } } },
            "is_additive": { "type": "boolean" },
            "is_hidden": { "type": "boolean" },
            "synonym_type": { "enum": ["USER_DEFINED", "AUTO_GENERATED"] },
            "data_panel_column_groups": { "type": "object" }
          }
        },
        "formula": {
          "type": "object",
          "properties": {
            "id": { "type": "string" },
            "expr": { "type": "string" },
            "was_auto_generated": { "type": "boolean" }
          }
        }
      }
    }
  }
}
```

## Reverse-direction rules (`Ossie → TML`)

These are the TML invariants a generator must satisfy. Each comes from a real import
failure recorded in the two TML references, so none is stylistic.

- **R1 `db_column_name`: always include on every table column, even when it equals
  `name`.** Some ThoughtSpot instances reject the import without it.
- **R2 `guid`: omit it on generated TML.** When updating an object in place, `guid:` goes
  at the **document root — NOT nested inside `table:` or `model:`**. A nested `guid:` is
  *silently ignored* and ThoughtSpot creates a duplicate object with the same name; this
  is the most common cause of "my update created a second model".
- **R3** Every formula is one `formulas[]` entry plus one `columns[]` entry referencing it
  by `formula_id` (exact, case- and space-sensitive). A `formulas[]` entry never carries
  `aggregation:`. Formula cross-references use the id form `[formula_<Name>]`, never the
  display-name form — a display-name reference fails on first import (ThoughtSpot parses
  it as search tokens), while id references resolve order-independently in a single pass.
- **R4** A metric is always emitted as a formula, never as a physical `column_id` plus an
  `aggregation`. Three reasons, each independently sufficient: (a) the same physical
  column is usually also a field, and two `columns[]` entries sharing a `column_id` is a
  `duplicate column_id` import error; (b) `aggregation: COUNT_DISTINCT` on a physical
  column makes ThoughtSpot **silently override** `column_type` to `ATTRIBUTE` — the
  documented fix is a `unique count ( [T::c] )` formula; (c) `aggregation` on a formula
  column is ignored at query time, so the aggregation has to be inside `expr` regardless.
  The source shape is recorded in the stash (`shape`) so a round trip reproduces the
  original document.
- **R5** Inline joins live inside the source (FK) `model_tables[]` entry, never at model
  top level (`destination is missing`). Quote the condition key as `'on':` — `on` is a
  YAML 1.1 reserved word. `type` and `cardinality` are both required; `with:` must equal
  the target entry's `name` exactly; `FULL_OUTER` becomes `OUTER` in a model inline join.
- **R6** `column_id` is `TABLE_NAME::Column Name`, where the prefix is the
  `model_tables[]` `name` or `alias` and the suffix is the Table document's column
  `name`. No two `columns[]` entries may share a `column_id`, and display names must be
  unique across `columns[]` and `formulas[]` (ID4).
- **R7** `column_type` goes under `properties:` — a bare `column_type` raises
  `No enum constant ColumnTypeEnum`. `synonyms` likewise goes under `properties:` (a
  root-level `synonyms:` is silently dropped) together with
  `synonym_type: USER_DEFINED`.
- **R8** Never set `is_hidden: true` when generating a model — hidden columns cause locked
  visualisations and surprising query behaviour, and visibility is the model owner's
  decision. Never set `was_auto_generated: true`.
- **R9** A formula `expr` containing `{ }` must be written as a `>-` block scalar, or the
  YAML fails to parse.
- **R10** Emit the `table:`/`sql_view:` documents and the `model:` document as one set;
  the Model references each table by name, so the tables must exist first.
- **R11** Serialise with YAML 1.2 boolean semantics. A ThoughtSpot column name, synonym or
  parameter value of `on`, `off`, `yes` or `no` is coerced to a boolean by a YAML 1.1
  reader on either read or write, which silently corrupts it.

## Explicit non-mappings

Deliberately not carried. In every case a value present on the source side raises an
issue naming the object and the construct — never a silent drop.

1. **NM1 — Object identity: `guid`, `obj_id`, and `model_tables[].fqn`.** These identify
   an object *inside one ThoughtSpot instance*. Carrying them into an interchange
   document would make it non-portable and re-importing a stale value fails with
   `fqn resolution failed`. Never emitted, never consumed, and absent from the payload
   schema by rule **X8**.
2. **NM2 — Row-level security (Table `rls_rules`).** These are access-control policy, not
   semantics: the rule expressions reference group identifiers that only exist in the
   source instance (e.g. `ts_groups_int`). Relocating a security policy into a portable
   document that other tools will read and rewrite is a hazard, not a convenience.
   `TML → Ossie` raises an issue naming each table that had rules, so the loss is
   visible. The model-scope `is_bypass_rls` *flag* is a different thing — a boolean whose
   loss would change results — and is stashed.
3. **NM3 — Presentation artifacts: Answers, Liveboards, charts.** Separate TML object
   types with their own identity. Ossie models semantics, not visualisations.
4. **NM4 — Spotter coaching objects: reference questions, feedback, business terms.**
   Separate TML object types that bind search tokens to phrasings. Ossie's
   `ai_context.examples` (`core-spec/spec.md:633-635`) is the nearest concept but is not
   interchangeable with them, so `examples` on any object raises an issue on
   `Ossie → TML` rather than being written somewhere approximate.
5. **NM5 — Aggregate-model associations (`aggregated_models`).** A query-routing
   performance optimisation whose entries are GUIDs of *other* Model objects:
   instance-local by construction (NM1) and not semantics. It is called out separately
   because stripping it silently disables the routing with no error, so the issue is the
   only signal a reader gets.
6. **NM6 — Legacy Worksheets, Views, Sets, and Alerts.** A `worksheet:` document
   (columns in `worksheet_columns[]`) is the Model's predecessor; `view:`, Sets and
   Alerts are separate object types layered on top of a model. A converter rejects these
   documents with a clear issue rather than half-mapping them into a Model.

## Open questions and upstream asks

| # | Ask | Why |
|---|---|---|
| **A1** | Add `THOUGHTSPOT` to the `Dialect` enum (`osi-schema.json:24-27`, `core-spec/spec.md:52-60`) **and** to `SKIP_SQL_VALIDATION` (`validation/validate.py:75`). | **Blocking.** The enum is closed, so a `THOUGHTSPOT` dialect entry fails schema validation today; and a ThoughtSpot formula is not SQL, so an unlisted dialect falls through to a default-dialect sqlglot parse and a hard error. Same treatment as `MDX`, `TABLEAU` and `MAQL` already receive. |
| **A2** | Add a `THOUGHTSPOT` row to the well-known vendor examples table (`core-spec/spec.md:439-448`). | Trivial, and it is the table a reader consults to know the extension key is legitimate. |
| **A3** | A core `filters` construct (or a documented convention). | The expression-language proposal already assumes one twice: it scopes itself to "expressions at the logical layer. This means metrics, fields, filters, etc" (`core-spec/expression_language.md:41`) and redirects `WHERE` to "the filter property" (`:130`) — but the core schema defines no such property. ThoughtSpot has `filters[]` and `constraints`; the Databricks Metric View has `filter`. All are stashed today, and a stashed filter is invisible to other consumers — so the same model returns different numbers in two tools. This is the highest-value semantic gap we found. |
| **A4** | Join `type` and cardinality on `Relationship`. | Every vendor is stashing them: Databricks derives cardinality from `from`/`to` orientation (`converters/databricks/README.md:84`), and ThoughtSpot has four cardinality values and five join types that orientation alone cannot encode. Is a core field in scope for 0.2.x? |
| **A5** | Confirm `label` semantics. | We read `field.label` as the human display label, matching the Databricks converter's `label` → `display_name` mapping (`converters/databricks/README.md:89`). `core-spec/spec.md:236` describes it as "Label for categorization", which reads differently. ThoughtSpot needs a display-label home because its display names are not valid SQL identifiers. |
| **A6** | Non-equality relationships. | `from_columns`/`to_columns` can only express FK equality. ThoughtSpot supports range and ASOF joins (timezone bridges, SCD-2 windows, point-in-time lookups) that are structural, not incidental, and today they cannot become relationships at all. `core-spec/expression_language.md:41` anticipates "arbitrary join expressions" — is that the intended home? |
| **A7** | Is deriving `primary_key` from a relationship's `to_columns` acceptable? | TML has no key declaration, so the only key evidence available is the join graph. The alternative is to omit `primary_key` unless a caller supplies it. Upstream's Databricks converter recovers `unique_keys` from a join hint (`converters/databricks/README.md:85`), which suggests derivation is accepted practice. |
| **A8** | Should `converters/README.md` tell an import converter to run `validation/validate.py` on its own emitted Ossie document? | Step 1 covers validating a *source* model; step 9 covers the *vendor* output against *vendor* tooling. Nothing tells a converter to validate the Ossie document it produces, even though `validate.py`'s four checks are exactly the invariants that output must satisfy. |

---

## Worked shape

One dataset, one attribute, one metric — the minimum that exercises the 1 + N document
split, the identifier rules, and the metric-as-formula rule (**R4**) — plus one deliberate
`lossy→issue`, so the example shows what a declared loss looks like rather than only the
clean path.

Ossie:

```yaml
version: 0.2.0.dev0
semantic_model:
  - name: sales_analytics
    description: Sales analytics model
    datasets:
      - name: orders
        source: SALES.PUBLIC.ORDERS
        primary_key: [ORDER_ID]   # deliberate lossy→issue — see the note below
        fields:
          - name: order_date
            label: Order Date
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: O_ORDERDATE
            datatype: Date
          - name: amount
            label: Amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: O_TOTALPRICE
            datatype: Decimal
        custom_extensions:
          - vendor_name: THOUGHTSPOT
            data: '{"_v": 1, "connection_name": "My Snowflake", "tml_object": "table"}'
    metrics:
      - name: total_revenue
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(orders.amount)
        datatype: Decimal
        ai_context:
          synonyms: ["revenue", "total sales"]
```

**`primary_key` is the demonstrated loss, and it is why neither TML document below mentions
`ORDER_ID`.** Per the Dataset-level `primary_key` row, TML has no key declaration anywhere,
so the only `Ossie → TML` home for a key is the join graph — and this model has a single
dataset and no relationships, which makes `[ORDER_ID]` the row's *unused key* case: nothing
consumes it, per **X9** nothing can stash it, so the converter raises an issue naming the
dataset and the dropped key rather than dropping it silently. (`ORDER_ID` is a physical
column of `SALES.PUBLIC.ORDERS`, not a declared field — Ossie's `primary_key` names key
*columns*, `osi-schema.json:188-193` — so its absence from `fields` is correct, not a
dangling reference.) Add a second dataset and a `MANY_TO_ONE` relationship into `orders`
and the same key becomes `lossless (join-derived)`: it is then recoverable from the
relationship's `to_columns` on the way back.

ThoughtSpot, Table document:

```yaml
table:
  name: ORDERS
  db: SALES
  schema: PUBLIC
  db_table: ORDERS
  connection:
    name: My Snowflake
  columns:
  - name: Order Date
    db_column_name: O_ORDERDATE
    properties:
      column_type: ATTRIBUTE
    db_column_properties:
      data_type: DATE
  - name: Amount
    db_column_name: O_TOTALPRICE
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX
    db_column_properties:
      data_type: DOUBLE
```

ThoughtSpot, Model document (no `guid` — **R2**):

```yaml
model:
  name: sales_analytics
  description: Sales analytics model
  model_tables:
  - name: ORDERS
  columns:
  - name: Order Date
    column_id: ORDERS::Order Date
    properties:
      column_type: ATTRIBUTE
  - name: Amount
    column_id: ORDERS::Amount
    properties:
      column_type: ATTRIBUTE
  - name: total_revenue
    formula_id: formula_total_revenue
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
      synonyms:
      - revenue
      - total sales
      synonym_type: USER_DEFINED
  formulas:
  - id: formula_total_revenue
    name: total_revenue
    expr: sum ( [ORDERS::Amount] )
  properties:
    join_progressive: true
    spotter_config:
      is_spotter_enabled: true
```

Note in the Model document: the metric is a formula, not `column_id: ORDERS::Amount` with
`aggregation: SUM` (**R4a** — that would collide with the `Amount` field's own entry);
`Amount` stays an `ATTRIBUTE` column so it remains referenceable; and the aggregation
lives in `expr`, with the column-level `aggregation` present only as the conventional
`SUM` that ThoughtSpot ignores at query time.
