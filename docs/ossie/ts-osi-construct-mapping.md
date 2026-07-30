# ThoughtSpot TML ↔ Ossie construct mapping

**Status:** post-ready (last touched 2026-07-30) — internally reviewed and complete; publication
to apache/ossie#285 is **held pending legal review**, and nothing has been posted
· **Ossie spec version:** `0.2.0.dev0`
(`core-spec/spec.yaml:20`, `core-spec/spec.md:24`; all Ossie citations below are
`path:line` against apache/ossie @ `c26b61c`) · **TS ground truth:**
`agents/shared/schemas/thoughtspot-model-tml.md`,
`agents/shared/schemas/thoughtspot-table-tml.md` and
`agents/shared/schemas/thoughtspot-view-tml.md` — internal paths in the ThoughtSpot
skills repo, cited below by section name as the *Model TML reference*, the
*Table TML reference* and the *View TML reference*. They are the authoritative record of
ThoughtSpot's TML shape (derived from real import failures, and since 2026-07-30 also from a
500-document census of real exported TML) and override any other description of it.

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
   dataset, so every computed field needs an attribution decision (see [Field and metric level](#field-and-metric-level)).

A ThoughtSpot **Worksheet** (root key `worksheet:`, columns in `worksheet_columns[]`) is
the predecessor of the Model and is deliberately out of scope — see non-mapping [**NM6**](#explicit-non-mappings).

## Direction naming and fidelity vocabulary

Directions are always written out: **`TML → Ossie`** (converter entry point
`tml_to_ossie`) and **`Ossie → TML`** (`ossie_to_tml`).

**How to read the fidelity column**

Every row answers one question: *if this ThoughtSpot construct goes through the converter, what happens to it?* Three outcomes:

| Verdict | What happens | Example |
|---|---|---|
| `lossless` | Both formats have a home for it — converts cleanly, no caveats | a column's name |
| `via custom_extensions` | Ossie has no field for it, so it travels in the `THOUGHTSPOT` vendor extension. Other tools ignore it; a return trip to ThoughtSpot restores it exactly | a column's `index_type` |
| `lossy→issue` | It cannot be carried at all. The converter drops it **and reports it** — a structured issue names the object and what was lost. Nothing is ever dropped silently | RLS rules |

Some constructs behave differently depending on the input. Two symbols cover that:

- **`/` means "depends which case you have"** — exactly one side applies to any given input.
  `lossless (physical) / lossy→issue (formula)` = a physical column converts cleanly; a formula-backed one raises an issue. One or the other, never both.
- **`+` means "both happen at once."**
  `lossy→issue + via custom_extensions (multi-dataset)` = for that case the converter raises the issue *and* stashes the value — the loss is reported, but nothing is thrown away.

The parenthetical just names the case the verdict applies to. `lossless (equi-join)` isn't a weaker lossless — it's lossless *for equi-joins*, and the same row says what happens outside that case.

Two more shapes appear in the Fidelity column. **`mixed`, used alone**, marks a *container* row (e.g. `fields`, `metrics`, `relationships`) whose real verdicts live in that construct's own table below — note this is distinct from the word "mixed" appearing as a **case name** in a parenthetical, as in `via custom_extensions (mixed)`, where it describes a join condition mixing equality and non-equality predicates. And a verdict may be a **pointer** — `per-function — see Expression handling` — used where one verdict cannot hold because it is decided separately for each function in an expression.

### The stash is asymmetric — and that matters for what "lossless" can mean

`custom_extensions` is an *Ossie* construct (`core-spec/spec.md:420-430`). TML has no
vendor-extension field of any kind. So:

- **`TML → Ossie → TML` is the round trip the stash makes lossless** — except for the
  explicit non-mappings [**NM1**–**NM6**](#explicit-non-mappings), which are deliberately not carried in either
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
| `name` | `model.name` | Normalised per [ID1](#identifiers--the-second-non-obvious-thing); when normalisation changed it, the exact ThoughtSpot name is stashed as `tml_name` | lossless |
| `description` | `model.description` | | lossless |
| `ai_context` (string form, or its `instructions` key) | Model-scope Spotter instructions | ThoughtSpot's model-scope instruction surface is configured **outside** the Model TML document — the Model TML reference documents no field for it, and per-column `properties.ai_context` is the only in-TML AI-context surface. `TML → Ossie` has nothing to read; `Ossie → TML` cannot write it | lossy→issue |
| `ai_context.synonyms` | — | No model-scope synonym field in Model TML (`properties.synonyms` exists on columns only) | lossy→issue |
| `ai_context.examples` | — | Example questions exist in ThoughtSpot as separate objects with their own identity, not as Model fields — see [**NM4**](#explicit-non-mappings) | lossy→issue |
| `datasets` | `model_tables[]` + one `table:`/`sql_view:` document per entry | 1 + N documents. The `model_tables[]` entry carries the join graph and the instance-local reference (`fqn`/`obj_id`), which is never round-tripped — see [**NM1**](#explicit-non-mappings) | lossless (structure) |
| `relationships` | Table `joins_with[]` (referenced from the Model by name) or `model_tables[].joins[]` (inline) | See [Relationship level](#relationship-level) | mixed |
| `metrics` | `formulas[]` + the `columns[]` entries that surface them (`formula_id`, `column_type: MEASURE`) | See [Metrics](#metrics) | mixed |
| `custom_extensions` | The `THOUGHTSPOT` entry is the payload below; entries for other vendors are passed through untouched in both directions | Following `converters/README.md`'s own edge-case guidance (preserve unknown-vendor entries rather than discard them) | lossless / via custom_extensions |

Model-scope ThoughtSpot-only constructs — `properties` (`is_bypass_rls`,
`join_progressive`, `spotter_config.is_spotter_enabled`), `parameters[]`, `filters[]`,
`constraints`, `column_groups[]`, `lesson_plans[]`, and model-level `joins_with[]`
data-augmentation joins — have no Ossie field and travel `via custom_extensions` (payload
keys below). Model scope is also where a join that cannot become a `Relationship` at all
comes to rest (`unrepresentable_joins[]` — see *Non-equality joins*).
`filters[]` and `constraints` are the semantically loudest of these: a stashed filter is
invisible to a non-ThoughtSpot consumer, so the same model can return different numbers
in two tools. That is upstream ask [**A3**](#open-questions-and-upstream-asks).

## Dataset level

Ossie schema: `core-spec/spec.md:124-133`; required keys `name` and `source`
(`osi-schema.json:225`).

| Ossie | ThoughtSpot | Direction notes | Fidelity |
|---|---|---|---|
| `name` | Table `table.name`, which must equal the `model_tables[]` `name` exactly (case-sensitive) | **One dataset per participating entry, not per physical table.** When one physical table participates twice (self-join, or one dimension in two roles) each `model_tables[]` entry carries a distinct `alias` and `column_id` prefixes use the alias (Model TML reference, *`model_tables[]` fields*). Each alias is its own Ossie dataset with the same `source`; `alias` and the underlying table name are stashed so the return trip rebuilds aliases instead of duplicate Table objects | lossless / via custom_extensions (alias) |
| `source` | `db` + `schema` + `db_table`, joined as `DB.SCHEMA.TABLE`; or, for a `sql_view:`, the `sql_query` string | Ossie explicitly allows `source` to be a query (`core-spec/spec.md:127`), so a `source` that is not a three-part identifier becomes a `sql_view:` document. The parts are stashed individually when any part contains a `.` and the dotted form would be ambiguous | lossless |
| (`source`'s warehouse binding) | Table `connection.name` | ThoughtSpot reaches the warehouse through a **named Connection object**; the Table TML reference requires `connection.name` (a display name, never a GUID, and `fqn:` inside a connection block must never appear). Ossie has no connection concept → stashed as `connection_name`. `Ossie → TML` cannot emit a valid Table document without one, so a hand-authored Ossie document with no stash requires the connection name as a converter argument; absent both, `lossy→issue` | via custom_extensions |
| `primary_key` | no key declaration exists in Table TML | `TML → Ossie`: derived — the ordered `to_columns` of relationships that target this dataset with a to-one cardinality are its key evidence; omitted when not derivable. `Ossie → TML`: a key that no relationship uses has nowhere to go. Upstream precedent binds the same pair to a join hint (`rely.at_most_one_match`, `converters/databricks/README.md:85`); TML has no equivalent hint. See ask [**A7**](#open-questions-and-upstream-asks) | lossless (join-derived) / lossy→issue (unused keys) |
| `unique_keys` | no key declaration exists in Table TML | Never emitted `TML → Ossie` — nothing in TML distinguishes a unique key from a join target. Dropped with an issue on the way in | lossy→issue |
| `description` | Table `table.description` | Documented in the Table TML reference, *`columns[]` fields* (the `table.description` row) | lossless |
| `ai_context` | — | No table-scope synonym or instruction field in Table TML | lossy→issue |
| `fields` | Table `columns[]`, surfaced by the Model `columns[]` entries whose `column_id` prefix is this dataset, plus ATTRIBUTE `formulas[]` attributed to it | See [Field and metric level](#field-and-metric-level). Table columns the Model does not surface are not part of the semantic model, so they are not emitted as fields; they are stashed as `unsurfaced_columns` so the Table document can be regenerated exactly | mixed |
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
| `from_columns` / `to_columns` | parsed from the join condition: `[FROM::a] = [TO::x] and [FROM::b] = [TO::y]` → ordered pairs | Ossie requires equal-length, order-corresponding arrays (`core-spec/spec.md:195-198`). **The boundary is non-equality joins:** ThoughtSpot supports range and ASOF joins using `>=`, `>`, `<`, `<=` and mixed predicates (Model TML reference, *Range / Inequality Joins*) for timezone bridges, SCD-2 effective-date windows and point-in-time lookups. These cannot be expressed as FK column pairs, so the condition is split on its top-level `and`s and the two cases are handled differently — see [**Non-equality joins**](#non-equality-joins--emit-the-relationship-carry-the-rest-as-an-extension) below. Ask [**A6**](#open-questions-and-upstream-asks) remains the request for first-class support | lossless (pure equi-join) / via custom_extensions (mixed) / lossy→issue (pure non-equi) |
| (join `type`) | `INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, `OUTER` — the **same four in both** the model inline join and the Table `joins_with[]` entry | No Ossie field. Stashed per relationship; `Ossie → TML` defaults to `INNER` when no stash is present, which matches an FK-equality relationship's semantics. **`OUTER` *is* ThoughtSpot's full outer join** (per ThoughtSpot domain review, 2026-07-30) — it is the name, not a narrower join. `FULL_OUTER` is not a ThoughtSpot value in *either* context and is rejected identically in both (live-verified 2026-07-30 on `se-thoughtspot`; error 14528, allowed values `INNER, LEFT_OUTER, OUTER, RIGHT_OUTER`), so a source `FULL OUTER` is emitted as `OUTER` everywhere — a rename, not a downgrade | via custom_extensions |
| (cardinality) | `MANY_TO_ONE`, `ONE_TO_ONE`, `ONE_TO_MANY`, `MANY_TO_MANY` | Ossie encodes cardinality only through orientation. `MANY_TO_ONE` maps to `from`→`to` directly; `ONE_TO_MANY` inverts the orientation; `ONE_TO_ONE` and `MANY_TO_MANY` have no orientation encoding at all. The value is stashed in every case and restored verbatim. Upstream does the same derivation in reverse (`converters/databricks/README.md:84`). See ask [**A4**](#open-questions-and-upstream-asks) | via custom_extensions |
| `ai_context` | — | No join-scope AI context in TML | lossy→issue |
| `custom_extensions` | relationship-scope payload below | | via custom_extensions |

### Non-equality joins — emit the relationship, carry the rest as an extension

Earlier drafts of this document declined to emit a `Relationship` at all whenever the join
condition was not a pure equality. That is stricter than it needs to be. Per guidance from
an Ossie committer on the community Slack, 2026-07-30, range and constant join support
should live "as an extension inside the relationships section … for now until we update the
spec to support those" — so the rule below carries the predicate on the relationship rather
than withholding the relationship.

The condition is split on its top-level `and`s into **equality pairs**
(`[FROM::a] = [TO::x]`) and **residual predicates** (everything else: `>=`, `>`, `<`, `<=`,
`between`, and comparisons against a literal constant rather than a column). Two cases follow,
and the dividing line is set by the schema, not by taste:

| Case | `TML → Ossie` behaviour | Fidelity |
|---|---|---|
| **At least one equality pair** (the common shape — an FK equality narrowed by an effective-date window, a timezone bridge, or a constant discriminator) | Emit the `Relationship`, with `from_columns`/`to_columns` carrying **only** the equality pairs. The residual predicates go into the relationship's own `custom_extensions` entry as `residual_predicates[]`, alongside the verbatim `on_expression`. An issue of severity `warning` records that the emitted relationship is **weaker than the source join** — a consumer that reads only `from_columns`/`to_columns` will join more rows than ThoughtSpot does | via custom_extensions |
| **No equality pair at all** (a pure range or pure constant join) | No relationship is emitted, because `from_columns` and `to_columns` are both `required` (`osi-schema.json:270`) **and** carry `minItems: 1` (`osi-schema.json:249`, `:257`) — a bare relationship with empty column arrays is a hard schema-validation failure, not a permitted degenerate form. The condition is stashed at model scope under `unrepresentable_joins[]` and an issue is raised. This is the **only** case that keeps the old model-scope-stash fallback | lossy→issue |

Two things make this safe to do:

- **`custom_extensions` is permitted on a `Relationship`.** It is a documented optional field
  of the construct — `core-spec/spec.md:191` ("`custom_extensions` | array | No |
  Vendor-specific attributes") and `osi-schema.json:263-268` — so the extension attaches to
  the relationship itself, not to some parent object standing in for it.
- **The emitted relationship is still valid, just under-specified.** The equality pairs are
  a true subset of the source condition, so `from`/`to`/`from_columns`/`to_columns` all
  describe a real FK equality; nothing fabricated is written. `Ossie → TML` reconstructs the
  full condition by re-joining the equality pairs with the stashed `residual_predicates[]`
  (or, better, by using the verbatim `on_expression` when present).

`Ossie → TML` for a hand-authored document with no stash emits the equality pairs only —
which is correct, because that is all the document says. The lost narrowing is a property of
the Ossie document, not of the converter, and that is exactly what [**A6**](#open-questions-and-upstream-asks) asks upstream to fix.

## Field and metric level

### Fields

Ossie schema: `core-spec/spec.md:231-240`; required keys `name` and `expression`
(`osi-schema.json:173`).

| Ossie | ThoughtSpot | Direction notes | Fidelity |
|---|---|---|---|
| `name` | `columns[].name`, normalised per [ID1](#identifiers--the-second-non-obvious-thing) | The exact display name round-trips through `label` | lossless |
| `label` | `columns[].name` verbatim | Read as the human display label, matching `converters/databricks/README.md:89`. See ask [**A5**](#open-questions-and-upstream-asks) | lossless |
| `expression` — a single bare identifier | Table `columns[].db_column_name`, surfaced by a Model `columns[]` entry with `column_id: TABLE::Name` and `column_type: ATTRIBUTE` | The identifier is the *physical* column; the display name comes from `label`/`name`. `db_column_name` is emitted unconditionally — see [**R1**](#reverse-direction-rules-ossie--tml) | lossless |
| `expression` — computed | Model `formulas[]` entry (`id: formula_<Name>`, `name`, `expr`) plus a `columns[]` entry referencing it by `formula_id` with `column_type: ATTRIBUTE` | ThoughtSpot formulas are model-scope, so a computed field must be **attributed** to a dataset: attribute it to the dataset all its column references resolve to. When they span two or more datasets there is no correct dataset, and the converter does not guess — it raises an issue and preserves the formula in the model-scope stash (`unattributed_formulas`). This mirrors upstream's refuse-to-guess rule for expressions on fanned-out datasets | lossless (single dataset) / lossy→issue + via custom_extensions (multi-dataset) |
| `expression.dialects[]` | one ThoughtSpot formula string | Each expression's verdict is decided function-by-function in the companion [function-mapping document](ts-osi-function-mapping.md#coverage-summary): of the 146 constructs the specification declares, **108 are `direct`** — a native ThoughtSpot equivalent, so that part of the expression is lossless; **37 are `passthrough`** — carried as warehouse SQL inside a `sql_*_op` wrapper, which preserves the result but couples it to one dialect; and **1 is `unmappable`** (`EXISTS_IN()`, unspecified upstream — ask [**A9**](ts-osi-function-mapping.md#open-questions-and-upstream-asks)), which raises an issue. An expression's verdict is therefore the weakest verdict among the constructs it uses. See [Expression handling](#expression-handling-summary--detail-in-the-companion-function-mapping-document) for how a formula is assembled and rewritten | per-function — see [Expression handling](#expression-handling-summary--detail-in-the-companion-function-mapping-document) |
| `dimension.is_time` (`is_time` is the `dimension` object's only key — `osi-schema.json:127-137`) | a `DATE` / `DATE_TIME` column, plus `properties.default_date_bucket` for its default grain | `TML → Ossie`: ThoughtSpot has no temporal-role flag, so the role is derived from the column type and `is_time` is emitted **only** when it differs from the type-derived default (`core-spec/spec.md:337`) — which, given a type-derived role, is never; the field is simply omitted and the default applies. `Ossie → TML`: a time role on a **non-temporal** type — a year as `Integer`, a quarter name as `String` (`core-spec/spec.md:341-348`) — has no TML flag to write and, per [**X9**](#protocol), nothing to stash → issue. **The issue is actionable, not just a report:** ThoughtSpot has no temporal-role flag, but it *can* hold a real `DATE` derived from the integer, so the issue carries a ready-to-paste formula for the common integer-year case rather than leaving the user to invent one — `to_date ( concat ( to_string ( [TABLE::Year] ) , '-01-01' ) , 'yyyy-MM-dd' )`, which anchors the year to 1 January (syntax live-verified 2026-07-30 on `se-thoughtspot`; a `trim ( )` negative control in the same pass was rejected, so formula bodies really are parsed by this check). Emit only the documented `yyyy-MM-dd` pattern style: the format string itself is **not** validated at import — a bogus `'%Y'` also passed — so acceptance proves the call shape, not the pattern. **The converter still does not synthesise by default**, because inventing a column is exactly what [**X9**](#protocol) forbids; whether to offer opt-in synthesis behind a flag (`--synthesize-time-columns`, emitting the formula as a real derived column and setting the temporal role) is a **Phase-3 converter decision**, to be settled with upstream feedback on whether a synthesised field should be marked as converter-generated. `properties.default_date_bucket` is a ThoughtSpot-only grain default, stashed in `column_properties` | lossless (temporal types) / lossy→issue (role on a non-temporal type) |
| — (no calendar concept in Ossie) | `properties.calendar` on a date column — the **custom / fiscal calendar** the column is bucketed by | ThoughtSpot lets a date column be reported against a non-Gregorian calendar (fiscal-year offset, 4-4-5 / 4-5-4 / 5-4-4 retail periods). **Only a reference travels, never a definition:** the calendar itself is a *Connection-scoped object* created outside TML via `POST /api/rest/2.0/calendars/create` (10.12.0.cl or later) and backed by a warehouse calendar table, so the Ossie document can record which calendar a column uses but cannot describe it. `TML → Ossie` stashes the value as `column_properties.calendar` and raises an issue naming the calendar, because a target instance without that calendar on that connection cannot honour the reference. `Ossie → TML` writes it back only from the stash — it is never invented. **The exact value vocabulary needs live verification ([V1](#thoughtspot-side-open-verifications-not-upstream-asks)):** ThoughtSpot's public TML documentation gives `calendar: [ default \| calendar_name ]` for Model columns, while our own SQL View reference records the literal `CALENDAR_TYPE_GREGORIAN`, and the two have not been reconciled — a converter must not emit this property until they are | lossy→issue (definition) + via custom_extensions (reference, pending [V1](#thoughtspot-side-open-verifications-not-upstream-asks)) |
| `description` | Model `columns[].description` for a Model-surfaced field; Table `columns[].description` for a Table-only one | **Live-verified 2026-07-30 on `se-thoughtspot`.** `description` is a first-class field on the Model `columns[]` entry and applies to a formula-backed entry exactly as it does to a `column_id` one — ThoughtSpot's own Model TML syntax lists `description: <optional_column_description>` as a `columns[]` key, and 14 of the 78 formula-backed columns in a 40-model random sample carry one (e.g. `What-If Sales` → "project sales figures based upon the input parameter percentage"). It is the `columns[]` entry, not the `formulas[]` entry, that owns column-level metadata; `formulas[]` holds only `id`/`name`/`expr`. So a computed field's description round-trips with no stash and no issue | lossless |
| `datatype` | Table `db_column_properties.data_type` | See [Datatype map](#datatype-map). **Live-verified 2026-07-30 on `se-thoughtspot`:** a formula-backed field has no *declared* type anywhere in Model TML — neither the `columns[]` entry nor the `formulas[]` entry has a `data_type` key in ThoughtSpot's documented syntax, and none of the 78 formula-backed columns in a 40-model sample carried one. ThoughtSpot derives a formula's type from its expression instead. So it is omitted `TML → Ossie` (`datatype` is optional) and raises an issue `Ossie → TML`. Note the physical case is also indirect: the type lives on the **Table** document, not the Model, so a Model-only reader cannot see it either | lossless (physical) / lossy→issue (formula) |
| `ai_context.synonyms` | `properties.synonyms` **plus** `properties.synonym_type: USER_DEFINED` | Both TML references warn that a `synonyms:` key at the column root is *silently dropped* on import — it must sit under `properties:`, and `synonym_type` must be set whenever synonyms are populated | lossless |
| `ai_context` string form / `instructions` | `properties.ai_context` | The Model TML reference documents `properties.ai_context` as the Spotter-facing context on a Model column | lossless |
| `ai_context.examples` | — | No per-column example store in TML — see [**NM4**](#explicit-non-mappings) | lossy→issue |
| `custom_extensions` | field-scope payload below (`index_type`, `geo_config`, `value_casing`, …) | | via custom_extensions |

### Metrics

Ossie schema: `core-spec/spec.md:365-372`; required keys `name` and `expression`
(`osi-schema.json:301`). Ossie metrics are **model-scope and may span datasets**
(`core-spec/spec.md:361`, and the cross-dataset example at `:403-416`) — exactly the
scope of a ThoughtSpot Model formula, so this level maps cleanly in both directions.

| Ossie | ThoughtSpot | Direction notes | Fidelity |
|---|---|---|---|
| `name` | `formulas[].name`, matched by the surfacing `columns[].name`, with `formulas[].id` = `formula_<Name>` and `columns[].formula_id` matching that id exactly | A `formulas[]` entry with no `columns[]` entry referencing it is **not surfaced** in the model at all (Model TML reference, *Formula Visibility*). Metrics have no `label` field, so when [ID1](#identifiers--the-second-non-obvious-thing) normalisation changes the name the exact ThoughtSpot display name is stashed | lossless / via custom_extensions (exact name) |
| `expression` | `formulas[].expr` | Always emitted as a formula, never as a physical column plus an aggregation — three grounded reasons in [**R4**](#reverse-direction-rules-ossie--tml) | lossless (translatable) / lossy→issue (untranslatable) |
| (the aggregation function, which lives *inside* `expression` — Ossie has no separate `aggregation` field) | `columns[].properties.aggregation` on the surfacing column | `TML → Ossie`: a `columns[]` entry with `column_id` + `aggregation: SUM` becomes the metric `SUM(dataset.field)`. The enum maps `SUM`/`COUNT`/`AVERAGE`/`MIN`/`MAX`/`COUNT_DISTINCT` ↔ `SUM`/`COUNT`/`AVG`/`MIN`/`MAX`/`COUNT(DISTINCT …)`, against Ossie's required core aggregations (`core-spec/expression_language.md:153-163`). TML also accepts `STD_DEVIATION`, `VARIANCE` and `NONE`, which map to Ossie's `STDDEV`, `VARIANCE` and "no aggregate" respectively. **`aggregation:` belongs in `columns[]` entries only — never in a `formulas[]` entry** (the Model TML reference records `FORMULA is not a valid aggregation type` as the resulting import error). Whether it *applies* on a formula column depends on the `expr`, and both directions need to know which: **a scalar `expr`** (`[FACT::AMOUNT] - [FACT::COST]`) is evaluated per row and then rolled up by the column's `aggregation`, exactly like a physical fact column with a default aggregation — so the column-level `aggregation` is load-bearing; **an aggregate `expr`** (`sum ( … )`) already carries its own aggregation and the column-level value is a no-op (*per ThoughtSpot domain review, 2026-07-30* — an earlier revision of this document stated the no-op case universally, which was wrong). `TML → Ossie` therefore composes the two: a scalar formula column carrying `aggregation: AVERAGE` becomes the metric expression `AVG(<translated scalar expr>)`, not the bare scalar. `Ossie → TML` may emit either shape — see [**R4**](#reverse-direction-rules-ossie--tml) | lossless |
| `description` | `columns[].description` on the surfacing column | **Live-verified 2026-07-30 on `se-thoughtspot`.** The `formulas[]` entry has no `description` key, but the `columns[]` entry that surfaces it does, and it is populated on real UI-authored metrics (14 of 78 formula-backed columns in a 40-model random sample). Since a metric is only surfaced *through* a `columns[]` entry (see the `name` row), that entry is always available as the description's home — so no stash and no issue | lossless |
| `datatype` | metrics have no declared type in Model TML | **Live-verified 2026-07-30 on `se-thoughtspot`:** no `data_type` key exists on either the `columns[]` or the `formulas[]` entry in ThoughtSpot's documented Model TML syntax, and none of the 78 sampled formula-backed columns carried one — ThoughtSpot derives a metric's type from its expression. `TML → Ossie` therefore emits `datatype` only when the metric is a bare aggregate over a typed physical column (`COUNT` and `COUNT(DISTINCT …)` → `Integer`; otherwise the column's mapped type); otherwise omitted. `Ossie → TML` has nowhere to write it ([**X9**](#protocol)) → issue | lossless (bare aggregate) / lossy→issue (otherwise) |
| `ai_context.synonyms` | `properties.synonyms` + `synonym_type` on the surfacing column | | lossless |
| `ai_context` string form / `instructions` | `properties.ai_context` on the surfacing column | `examples` is unsupported — see [**NM4**](#explicit-non-mappings) | lossless / lossy→issue (`examples`) |
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
| `Decimal` | `DOUBLE` | `DOUBLE` → `Decimal` | ThoughtSpot has a single approximate numeric type, so `Decimal` and `Float` **collapse** into it. `TML → Ossie → TML` is exact (`DOUBLE` → `Decimal` → `DOUBLE`); `Ossie → TML → Ossie` cannot distinguish the two, and per [**X9**](#protocol) no stash can recover it → **declared loss**, reported as an issue when the input said `Float` |
| `Float` | `DOUBLE` (`FLOAT` on a BigQuery-backed connection) | `FLOAT` → `Float` | The Table TML reference distinguishes `DOUBLE` for Snowflake-style numerics from `FLOAT` for BigQuery. A `FLOAT` column round-trips exactly; a `DOUBLE` one comes back as `Decimal` (row above) |
| `Boolean` | `BOOLEAN` (`BOOL` on a Snowflake-backed connection) | `BOOL` / `BOOLEAN` → `Boolean` | Lossless. The Table TML reference gives `BOOLEAN` as the general value and `BOOL` as the Snowflake-specific one, so `BOOLEAN` is the default and `BOOL` is selected from the connection. Which spelling the connection uses is recorded in the field stash's `data_type` key so the return trip re-emits the same one |
| `Date` | `DATE` | `DATE` → `Date` | Lossless |
| `Time` | `VARCHAR`, or `DATE_TIME` when the underlying column is timestamp-backed | — never emitted | ThoughtSpot's documented `data_type` set (Table TML reference, *Data Type Mapping*) has no time-of-day type at all — the closest values are `DATE`, `DATE_TIME` and `VARCHAR`. Per [**X9**](#protocol) the original cannot be stashed, so this is a **declared loss** reported at conversion time |
| `DateTime` | `DATE_TIME` | `DATE_TIME` → `DateTime` | Lossless |
| `DateTimeTz` | `DATE_TIME` | — (see `DateTime`) | ThoughtSpot has no offset-aware column type — display time zone is an instance/user setting, not a column property. `Ossie → TML → Ossie` collapses to `DateTime` → **declared loss**, reported at conversion time |
| `Opaque` | `VARCHAR` | — never emitted | Ossie's escape hatch for a type outside the portable vocabulary (`core-spec/spec.md:80`). The marker collapses to `String` on a return trip → **declared loss**, reported at conversion time. Any accompanying vendor refinement in a foreign-vendor extension passes through untouched ([**X7**](#protocol)) |
| *(omitted)* | derived from the warehouse; `INT64` when a numeric column's precision is unknown, per the Table TML reference's guidance to prefer `INT64` and let ThoughtSpot report a mismatch | omitted | `datatype` is optional on both sides; omission is a legitimate value, not a gap |

**Reverse-direction rule:** every Table column carries `db_column_properties.data_type`.
ThoughtSpot raises `Compulsory Field table->columns->db_column_properties is not
populated` when the block is absent, so an Ossie field with no `datatype` still needs one
inferred rather than omitted.

## Expression handling (summary — detail in the companion function-mapping document)

1. **Reference rewriting** — `[TABLE::Column]` ↔ `dataset.field` ([**ID3**](#identifiers--the-second-non-obvious-thing)). Never a textual
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
   `filters[]` and `constraints` therefore have no Ossie home (ask [**A3**](#open-questions-and-upstream-asks)).
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
  These are instance-local (see [**NM1**](#explicit-non-mappings)); a portable document must not contain them, and
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
        "lesson_plans": {
          "type": "array",
          "description": "Verbatim model.lesson_plans[] entries (lesson_id, lesson_plan_string) — the in-product guided-lesson strings attached to a Model. No Ossie equivalent; presentation/coaching content, but TML-resident and therefore stashable (unlike the separate coaching objects of NM4). Shape live-confirmed on 8 real Models (2026-07-30 census); lesson_id is 0-based.",
          "items": { "type": "object" }
        },
        "action_object_associations": {
          "type": "array",
          "description": "Verbatim model.action_object_associations[] entries ({action_name, context, enabled}) — custom actions bound to the Model, e.g. {\"action_name\": \"Generate Forecast\", \"context\": \"CONTEXT_MENU\", \"enabled\": true}. Found by the 2026-07-30 census (1 of 143 Models) and previously undocumented anywhere in this repo. Classified as a presentation binding, so NM3's reasoning applies to the ACTION — the custom action itself is a separate object type and is not converted — but the ASSOCIATION is TML-resident, so it is stashable on the same basis as lesson_plans rather than dropped. It names the action by display name only, so it is a no-op on an instance lacking an action of that name; Ossie -> TML must therefore not invent one, and an inbound association whose action cannot be resolved raises an issue rather than being written.",
          "items": { "type": "object" }
        },
        "model_joins_with": {
          "type": "array",
          "description": "Verbatim model-level joins_with[] data-augmentation joins (e.g. an uploaded dataset joined to the model).",
          "items": { "type": "object" }
        },
        "unrepresentable_joins": {
          "type": "array",
          "description": "Joins with no equality pair at all (pure range or pure constant conditions), which cannot become a Relationship because from_columns/to_columns are required with minItems 1 (osi-schema.json:249, :257, :270). Preserved verbatim; an issue is raised alongside. A join with at least one equality pair does NOT appear here — it is emitted as a Relationship with its residual predicates in the relationship's own extension.",
          "items": {
            "type": "object",
            "required": ["from", "to", "on_expression"],
            "properties": {
              "from": { "type": "string" },
              "to": { "type": "string" },
              "on_expression": { "type": "string" },
              "type": { "type": "string" },
              "cardinality": { "type": "string" },
              "join_shape": { "enum": ["referencing", "inline", "referencing_with_inline_attrs"] },
              "referencing_join": { "type": "string" }
            }
          }
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
        "type": { "enum": ["INNER", "LEFT_OUTER", "RIGHT_OUTER", "OUTER"], "description": "ThoughtSpot's complete join-type vocabulary, identical in the Model inline join and the Table joins_with[] entry. OUTER is the full outer join; FULL_OUTER is not a ThoughtSpot value and is rejected in both contexts (error 14528, live-verified 2026-07-30)." },
        "cardinality": { "enum": ["MANY_TO_ONE", "ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_MANY"] },
        "join_shape": {
          "enum": ["referencing", "inline", "referencing_with_inline_attrs"],
          "description": "referencing = a named Table joins_with[] entry the Model points at; inline = defined in model_tables[].joins[]; referencing_with_inline_attrs = BOTH, which is real — 12 of 493 joins in a 143-Model census (2026-07-30) carry a referencing_join PLUS a `type` or a `cardinality`. The enum was closed at the first two values, which would have collapsed those hybrids to `referencing` and silently dropped the inline attribute. `type`/`cardinality` are independent keys here, so they survive whichever shape is recorded — the third value exists so `Ossie -> TML` can reproduce the source document rather than normalising it."
        },
        "referencing_join": { "type": "string", "description": "The Table joins_with[] name, when join_shape is referencing" },
        "on_expression": {
          "type": "string",
          "description": "The verbatim join condition. Required whenever the condition is not a pure equality (range / ASOF / constant joins), because from_columns/to_columns then carry only part of it. Preferred over re-assembling the condition from the pairs plus residual_predicates on the way back."
        },
        "residual_predicates": {
          "type": "array",
          "description": "The non-equality predicates of the join condition — the top-level `and` terms that are not a plain [FROM::col] = [TO::col] pair (>=, >, <, <=, between, or a comparison against a literal constant). Present only when the relationship WAS emitted, i.e. at least one equality pair existed; the equality pairs live in from_columns/to_columns and these are what those arrays cannot express. Per the community guidance of 2026-07-30 this is the interim home for range and constant join support, pending ask A6.",
          "items": { "type": "string" }
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
            "index_type": {
              "enum": ["DONT_INDEX", "DEFAULT", "PREFIX_ONLY", "PREFIX_AND_SUBSTRING", "PREFIX_AND_WORD_SUBSTRING"],
              "description": "Full documented set — a payload restricted to DONT_INDEX/PREFIX_ONLY would reject a model using the substring variants."
            },
            "index_priority": { "type": "number", "description": "Search-indexing priority. A NUMBER, not an integer: ThoughtSpot emits it non-integrally (`\"index_priority\":10.0`, confirmed in the raw edoc across all 20 sightings in a 2026-07-30 census), so an integer-typed field rejects real ThoughtSpot output." },
            "value_casing": { "enum": ["UPPER", "LOWER", "MIXED", "UNKNOWN"], "description": "Documented as a Table-column refinement on VARCHAR, but observed on 545 MODEL columns across 18 of 143 Models (2026-07-30 census), 156 of them formula-backed — so it is stashed at the field level for Model columns too, not only for Table ones." },
            "default_date_bucket": { "enum": ["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY", "AUTO"] },
            "calendar": {
              "type": "string",
              "description": "The custom / fiscal calendar the date column is bucketed by — a reference only; the calendar object itself lives on the Connection, outside TML. Value vocabulary SETTLED 2026-07-30 (V1): it is a calendar NAME, with the literal `calendar` as the default spelling; CALENDAR_TYPE_GREGORIAN was observed zero times in 500 documents. Honoured on Table and formula-backed columns as well as Model ones. A converter records it and still does not emit it, because the named calendar does not exist on a target instance."
            },
            "custom_order": { "type": "array", "items": { "type": "string" } },
            "geo_config": {
              "type": "object",
              "description": "Map-rendering role. FIVE shapes exist, confirmed by a 2026-07-30 census of 143 Models: `region_name` as a DICT {country, region_name} (88 sightings), `latitude: true` (17), `longitude: true` (17), `custom_file_guid` + `geometryType` (7), and `country: true` (5) — the last being a BARE BOOLEAN, distinct from `region_name.country`, which is a string. A geo_config that names a **custom map** carries `custom_file_guid` + `geometryType` — a GUID, so by rule X8 (and NM1) it must NOT be stashed: that column's geo role is dropped with an issue naming the custom map instead. Custom maps are confirmed present in production (3 Models), so this path is exercised, not hypothetical."
            },
            "spotiq_preference": { "type": "string" },
            "search_iq_preferred": { "type": "boolean" },
            "synonym_type": { "enum": ["USER_DEFINED", "AUTO_GENERATED"] },
            "is_hidden": { "type": "boolean", "description": "Preserved on round trip; never invented — see R8" },
            "is_additive": { "type": "boolean" },
            "is_attribution_dimension": { "type": "boolean" },
            "is_mandatory_token_filter": {
              "type": "boolean",
              "description": "ABAC: when true, a user with no filter rule for this column in their token is denied all data. Stashed for the same reason `is_bypass_rls` is (NM2) — it is a boolean whose loss changes results, and it fails **open**: drop it and those users see everything instead of nothing."
            },
            "format_pattern": { "type": "string" },
            "currency_type": {
              "type": "object",
              "description": "Exactly one of the three documented forms, which are mutually exclusive: a fixed ISO code, a per-row code taken from another column, or the viewer's browser locale. A payload allowing only iso_code silently drops the other two.",
              "properties": {
                "iso_code": { "type": "string" },
                "column": { "type": "string", "description": "Name of the column supplying the currency code per row" },
                "is_browser": { "type": "boolean", "description": "Format in the viewer's browser locale" }
              }
            },
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
      "description": "No key exists here for `description` or `datatype`, for two different reasons (both live-verified 2026-07-30). `description` needs no stash: it has a native Model-TML home on the surfacing columns[] entry, so it maps straight to the Ossie `description` field. `datatype` has no Model-TML home at all — a formula carries no declared type — so per X9 there is nothing for tml_to_ossie to read and nothing to stash.",
      "properties": {
        "tml_name": { "type": "string", "description": "Exact display name when normalisation changed it (metrics have no `label`)" },
        "shape": {
          "enum": ["formula", "scalar_formula_plus_aggregation", "column_aggregation"],
          "description": "Which TML shape the source used, so TML -> Ossie -> TML reproduces it. New TML is always emitted as `formula` today — see R4. `scalar_formula_plus_aggregation` is a formulas[] entry whose expr is scalar, aggregated by the surfacing columns[] entry's `aggregation`: it round-trips as AGG(scalar_expr) and is the Phase-3 emission option R4-P3 pattern B; recording it distinctly is what lets that round trip reproduce the source shape rather than collapsing it to `formula`."
        },
        "column_id": { "type": "string", "description": "TABLE::Column, when shape is column_aggregation" },
        "column_properties": {
          "type": "object",
          "properties": {
            "aggregation": {
              "enum": ["SUM", "COUNT", "AVERAGE", "MIN", "MAX", "COUNT_DISTINCT", "NONE", "STD_DEVIATION", "VARIANCE"],
              "description": "Full documented TML set. The first six are the enum the Metric-level table maps to Ossie's required core aggregations; STD_DEVIATION and VARIANCE map to Ossie's STDDEV / VARIANCE, and NONE means the column is surfaced unaggregated."
            },
            "index_type": { "enum": ["DONT_INDEX", "DEFAULT", "PREFIX_ONLY", "PREFIX_AND_SUBSTRING", "PREFIX_AND_WORD_SUBSTRING"] },
            "index_priority": { "type": "number", "description": "A number, not an integer — same reason as the FieldLevel entry: ThoughtSpot emits it non-integrally (10.0)." },
            "format_pattern": { "type": "string" },
            "currency_type": {
              "type": "object",
              "description": "One of the three mutually-exclusive forms — see the FieldLevel entry.",
              "properties": {
                "iso_code": { "type": "string" },
                "column": { "type": "string" },
                "is_browser": { "type": "boolean" }
              }
            },
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
  `aggregation`. Two reasons, each independently sufficient: (a) the same physical
  column is usually also a field, and two `columns[]` entries sharing a `column_id` is a
  `duplicate column_id` import error; (b) `aggregation: COUNT_DISTINCT` on a physical
  column makes ThoughtSpot **silently override** `column_type` to `ATTRIBUTE` — the
  documented fix is a `unique count ( [T::c] )` formula.
  **(c) — corrected, and no longer a reason.** An earlier revision of this rule gave a third
  reason: "`aggregation` on a formula column is ignored at query time, so the aggregation has to
  be inside `expr` regardless." *Per ThoughtSpot domain review, 2026-07-30* that is only true of
  an **aggregate** `expr`. On a **scalar** `expr` the column-level `aggregation` **does** apply —
  the formula is evaluated per row and rolled up by the declared aggregation, the same way a
  physical fact column with a default aggregation behaves. So R4 rests on (a) and (b) alone; (c)
  is retained here as a corrected note because the wrong version of it is quoted downstream (see
  **G11** in the [compliance-gaps document](ts-osi-compliance-gaps.md)).
  The source shape is recorded in the stash (`shape`) so a round trip reproduces the
  original document.
- **R4-P3** *(Phase-3 design option, recorded not decided.)* Because a scalar `expr` plus a
  column-level `aggregation` is a real ThoughtSpot idiom rather than a no-op, an Ossie metric
  of the form `AGG(<scalar expression>)` has **two** faithful TML emissions, and the choice is a
  Phase-3 converter design decision:

  | Pattern | Emission | Trade-off |
  |---|---|---|
  | **A — aggregate-in-expr** (today's rule) | one `formulas[]` entry, `expr: "sum ( [FACT::AMOUNT] - [FACT::COST] )"`; the surfacing `columns[]` entry's `aggregation` is a conventional no-op | One object per metric, and the metric's grain is fixed by the `expr`. Simplest, and what R4 emits today. |
  | **B — scalar formula + column aggregation** | one `formulas[]` entry, `expr: "[FACT::AMOUNT] - [FACT::COST]"`, and the surfacing `columns[]` entry carries `properties.aggregation: SUM` | More idiomatic ThoughtSpot, and **reusable at row grain**: the same formula can be re-aggregated differently in different searches and composed into other formulas, which pattern A forecloses. Costs a round-trip subtlety — the aggregation now lives in a *property*, so a `TML → Ossie` reader must compose it back (see the Metric-level `aggregation` row) or the metric silently loses its aggregate. |

  Pattern B is only available when the aggregation is a single outer aggregate over an otherwise
  scalar expression — `SUM(a - b)` qualifies, `SUM(a) / SUM(b)` does not (there is no scalar
  expression to hoist). A converter choosing B must also not emit a `SUM` on a scalar *ratio*
  expression, because the sum of per-row ratios is not the ratio of the sums.
- **R5** Inline joins live inside the source (FK) `model_tables[]` entry, never at model
  top level (`destination is missing`). Quote the condition key as `'on':` — `on` is a
  YAML 1.1 reserved word. `type` and `cardinality` are both required; `with:` must equal
  the target entry's `name` exactly; a source `FULL OUTER` / `FULL_OUTER` becomes `OUTER`,
  in **both** the model inline join and the Table `joins_with[]` entry — ThoughtSpot accepts
  only `INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, `OUTER` in either context, and `OUTER` *is* its
  full outer join, so this is a **semantics-preserving rename and never a loss** (per
  ThoughtSpot domain review, 2026-07-30; the rejection live-verified in both contexts the
  same day on `se-thoughtspot`).
- **R6** `column_id` is `TABLE_NAME::Column Name`, where the prefix is the
  `model_tables[]` `name` or `alias` and the suffix is the Table document's column
  `name`. No two `columns[]` entries may share a `column_id`, and display names must be
  unique across `columns[]` and `formulas[]` ([ID4](#identifiers--the-second-non-obvious-thing)).
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

1. **NM1 — Object identity: `guid`, `obj_id`, `model_tables[].fqn`, `table.dataset_id`, and
   `geo_config.custom_file_guid`.** These identify an object *inside one ThoughtSpot instance*.
   Carrying them into an interchange document would make it non-portable and re-importing a stale
   value fails with `fqn resolution failed`. Never emitted, never consumed, and absent from the
   payload schema by rule [**X8**](#protocol). Two additions from the 2026-07-30 census:
   **`table.dataset_id`** — a 12-hex-character root-level Table key (`28ede9b627ab`) on
   uploaded/derived tables, 4 of 275 observed, undocumented by ThoughtSpot and identity-shaped, so
   it joins this list rather than the stash; and **`geo_config.custom_file_guid`**, which was
   already excluded by X8 in the `geo_config` note and is named here so the list is complete.
2. **NM2 — Row-level security (Table `rls_rules`).** These are access-control policy, not
   semantics: the rule expressions reference group identifiers that only exist in the
   source instance (e.g. `ts_groups_int`). Relocating a security policy into a portable
   document that other tools will read and rewrite is a hazard, not a convenience.
   `TML → Ossie` raises an issue naming each table that had rules, so the loss is
   visible. **Two security *booleans* are carved out and stashed**, because unlike a rule
   expression they name no group and their loss would change results:
   model-scope `is_bypass_rls`, and column-scope `properties.is_mandatory_token_filter`
   (ABAC). The second is the sharper case — it **fails open**: with the flag set, a user
   whose token carries no filter rule for that column is denied all data; drop the flag and
   that same user sees every value instead of none. A silent drop would therefore *widen*
   access, so it is preserved and an issue is raised when it cannot be.
3. **NM3 — Presentation artifacts: Answers, Liveboards, charts.** Separate TML object
   types with their own identity. Ossie models semantics, not visualisations.
4. **NM4 — Spotter coaching objects: reference questions, feedback, business terms.**
   Separate TML object types that bind search tokens to phrasings. Ossie's
   `ai_context.examples` (`core-spec/spec.md:633-635`) is the nearest concept but is not
   interchangeable with them, so `examples` on any object raises an issue on
   `Ossie → TML` rather than being written somewhere approximate.
5. **NM5 — Aggregate-model associations (`aggregated_models`).** A query-routing
   performance optimisation whose entries are GUIDs of *other* Model objects:
   instance-local by construction ([NM1](#explicit-non-mappings)) and not semantics. It is called out separately
   because stripping it silently disables the routing with no error, so the issue is the
   only signal a reader gets.
6. **NM6 — Legacy Worksheets, Views, Sets, Alerts, and Model Alias objects.** A
   `worksheet:` document (columns in `worksheet_columns[]`) is the Model's predecessor;
   `view:`, Sets and Alerts are separate object types layered on top of a model. A
   standalone **Model Alias** is likewise its own object type — an instance-distribution
   artifact that points at a published master Model so other Orgs can use it without a
   copy, so it carries no semantics of its own; the master Model is the thing to convert.
   A converter rejects all of these documents with a clear issue rather than
   half-mapping them into a Model.

   Two refinements from a 500-document TML census on a current Cloud build (2026-07-30):

   - **`worksheet:` is no longer obtainable by export.** All 2,397 `WORKSHEET`-subtype objects on
     the surveyed cluster were checked: **2,394 carry `worksheetVersion: V2`** and every sampled
     one exported with root key `model:` — V2 *is* a Model. The only three without a
     `worksheetVersion` are ThoughtSpot's own system worksheets and all three return `FORBIDDEN`
     on export. The rule stays as a defensive check, but its likelihood of firing on a current
     build is near zero.
   - **A `view:` document is rejected, and the reason deserves the same explicitness
     `worksheet:` gets.** It is not that `view_columns[]` is hard to map — it is that
     **`view.search_query` carries the View's actual semantics.** Observed on **42 of 42** real
     Views, it is where the aggregation and the filtering live; `view_columns[]` only names and
     decorates the output columns of that search, and its column reference is a search-output
     *label* (`search_output_column`, e.g. `Total Revenue`, `Month(YM)`) rather than a
     `table_path::column` reference. A reader who mapped `view_columns[]` alone would produce a
     dataset with the right column names and none of the semantics. See the *View TML reference*.

     One consequence of the exclusion is worth recording rather than leaving implicit: a View
     column's `aggregation` vocabulary is **wider than the Model/Table one** — `MOVING_SUM`,
     `RANK` and `SQL_INT_AGGREGATE_OP` were all observed on real View columns, none of which is in
     the nine-value set the Metric level maps. The census verified the boundary in both
     directions: across all 500 documents, `model:` columns used only
     `{SUM, AVERAGE, COUNT, COUNT_DISTINCT, MIN}`, `table:` only
     `{SUM, AVERAGE, COUNT, COUNT_DISTINCT}` and `sql_view:` only `{SUM, AVERAGE}` — **no window
     value appears on any document type a converter accepts.** So the payload schema's
     nine-value `aggregation` enum is **correct as scoped and is deliberately not widened**; the
     wider vocabulary belongs to `view:`, which NM6 excludes.

## Open questions and upstream asks

Each ask carries the **upstream venue** it should be raised in — mapped against apache/ossie's existing discussion index on 2026-07-30, so an ask lands on a live thread rather than as a duplicate ticket.

| # | Ask | Why | Upstream venue |
|---|---|---|---|
| **A1** | Add `THOUGHTSPOT` to the `Dialect` enum (`osi-schema.json:24-27`, `core-spec/spec.md:52-60`) **and** to `SKIP_SQL_VALIDATION` (`validation/validate.py:75`). | **Blocking.** The enum is closed, so a `THOUGHTSPOT` dialect entry fails schema validation today; and a ThoughtSpot formula is not SQL, so an unlisted dialect falls through to a default-dialect sqlglot parse and a hard error. Same treatment as `MDX`, `TABLEAU` and `MAQL` already receive. | converter PR (or a short issue referencing #285) |
| **A2** | Add a `THOUGHTSPOT` row to the well-known vendor examples table (`core-spec/spec.md:439-448`). | Trivial, and it is the table a reader consults to know the extension key is legitimate. | converter PR |
| **A3** | A core `filters` construct (or a documented convention). | The expression-language proposal already assumes one twice: it scopes itself to "expressions at the logical layer. This means metrics, fields, filters, etc" (`core-spec/expression_language.md:41`) and redirects `WHERE` to "the filter property" (`:130`) — but the core schema defines no such property. ThoughtSpot has `filters[]` and `constraints`; the Databricks Metric View has `filter`. All are stashed today, and a stashed filter is invisible to other consumers — so the same model returns different numbers in two tools. This is the highest-value semantic gap we found. | discussion #5 (Semantic Filters) |
| **A4** | Join `type` and cardinality on `Relationship`. | Every vendor is stashing them: Databricks derives cardinality from `from`/`to` orientation (`converters/databricks/README.md:84`), and ThoughtSpot has four cardinality values and five join types that orientation alone cannot encode. Is a core field in scope for 0.2.x? | discussion #50 (Make Relationship Cardinality Explicit); related #11, #24 |
| **A5** | Confirm `label` semantics. | We read `field.label` as the human display label, matching the Databricks converter's `label` → `display_name` mapping (`converters/databricks/README.md:89`). `core-spec/spec.md:236` describes it as "Label for categorization", which reads differently. ThoughtSpot needs a display-label home because its display names are not valid SQL identifiers. | discussion #37 (Display name); related #31 |
| **A6** | First-class support for non-equality relationships. | `from_columns`/`to_columns` can only express FK equality. ThoughtSpot supports range and ASOF joins (timezone bridges, SCD-2 windows, point-in-time lookups) that are structural, not incidental. **Interim answer received, and this document now follows it:** per guidance from an Ossie committer on the community Slack, 2026-07-30, range and constant joins should be carried as "an extension inside the relationships section … for now until we update the spec to support those" — so a join with at least one equality pair is emitted as a `Relationship` with its residual predicates in the relationship's own `custom_extensions` (`core-spec/spec.md:191`). **The ask stays open** for two reasons: an extension is invisible to every consumer that does not read the `THOUGHTSPOT` vendor key, so the emitted relationship still over-joins for everyone else; and a **pure** range or constant join still cannot be expressed at all, because `from_columns`/`to_columns` are required with `minItems: 1` (`osi-schema.json:249`, `:257`, `:270`). `core-spec/expression_language.md:41` anticipates "arbitrary join expressions" — is that the intended permanent home? | discussion #4 (Complex Relationship Definitions) |
| **A7** | Is deriving `primary_key` from a relationship's `to_columns` acceptable? | TML has no key declaration, so the only key evidence available is the join graph. The alternative is to omit `primary_key` unless a caller supplies it. Upstream's Databricks converter recovers `unique_keys` from a join hint (`converters/databricks/README.md:85`), which suggests derivation is accepted practice. | converter PR review |
| **A8** | Should `converters/README.md` tell an import converter to run `validation/validate.py` on its own emitted Ossie document? | Step 1 covers validating a *source* model; step 9 covers the *vendor* output against *vendor* tooling. Nothing tells a converter to validate the Ossie document it produces, even though `validate.py`'s four checks are exactly the invariants that output must satisfy. | discussion #35 (OSI-level validations?) |

### ThoughtSpot-side open verifications (not upstream asks)

These are **ours to settle**, not requests to Ossie. Each is a ThoughtSpot TML property whose
existence is documented but whose exact shape or round-trip behaviour has not been verified
against a live instance, so a converter must record it and refuse to emit it. They came out of a
2026-07-30 sweep of ThoughtSpot's own product documentation against the TML references this
document is grounded in — the question being *which product features our references don't
mention*, which is the class of gap the `calendar` row above belongs to.

| # | Item | What is known | What needs verifying |
|---|---|---|---|
| **V1** | `properties.calendar` — custom / fiscal calendar on a date column | **SUBSTANTIALLY SETTLED 2026-07-30** by a 500-document census. The value is a calendar **name**: two real named calendars observed (`SeanTSCROOTS`, `Dupont_Fiscal_Cal`), with the literal `calendar` as the default spelling (70 sightings across 34 unrelated Models). `CALENDAR_TYPE_GREGORIAN` and `default` were observed **zero** times on any of the four document types. `calendar:` **is** honoured on a **Table** column (`FACT_RETAPP_SALES.RECORDDATE`) and on **formula-backed** Model columns (5 sightings). Custom calendars remain Connection-scoped objects created via `POST /api/rest/2.0/calendars/create` (10.12.0.cl+), none of whose configuration is in TML | **What remains: one question, narrowed.** Is the literal `calendar` a genuine default *sentinel*, or a customer calendar coincidentally named "calendar"? The 34-Model spread across unrelated tenants strongly favours sentinel. Closing it needs a `GET /api/rest/2.0/calendars/…` read on the surveyed cluster — census follow-up **T4**, not another export. **The converter behaviour this gated is now decided:** read and stash a calendar *name*; never emit; treat `CALENDAR_TYPE_GREGORIAN` as withdrawn |
| **V2** | `properties.currency_type` — the `column` and `is_browser` forms | **PARTIALLY SETTLED 2026-07-30.** The `column` form is confirmed live — one sighting, on a **Table** column, carrying a **bare column name** (`{"column": "TARGET_CURRENCY"}`), *not* a `TABLE::Column` reference. That answers half the open question. `is_browser` was observed **zero** times anywhere in 500 documents. All 81 Model sightings and all 5 View sightings used `iso_code` | Two things still open: whether either non-`iso_code` form survives an import/export **round trip** (the census is export-only, so it shows the form exists, not that it survives being written back), and whether `is_browser` is emitted at all on any build |
| **V3** | `geo_config` naming a **custom map** (`custom_file_guid` + `geometryType`) | **CONFIRMED PRESENT IN PRODUCTION 2026-07-30** — 3 Models / 7 columns in the census, with `geometryType` ∈ {`POLYGON`, `MULTI_POLYGON`}. Previously documented but unevidenced | Nothing to verify for the converter — rule **X8** already forbids stashing a GUID, so this stays settled as a declared loss. The census's contribution is that the declared-loss path is **exercised in the wild**, not hypothetical: real models will hit it. The census also found a **fifth** geo role this document did not name, `country: true` (a bare boolean, 5 sightings) — added to the `geo_config` payload description |
| **V4** | `properties.is_mandatory_token_filter` — ABAC mandatory filters | Documented: a user with no matching filter rule in their token is denied all data for that column. **Still unevidenced:** observed **zero** times in the 500-document census, so a second, much larger sample has now failed to find it | **STILL FULLY OPEN**, and the census cannot speak to it — a property that never appears cannot be shown to round-trip. That it survives a TML round trip at all remains untested, and it **fails open** if dropped, which is the worst direction for a security flag. It is stashed rather than ignored, but the stash is only as good as the export. Closing this needs a *constructed* object that sets the flag, not a wider survey |

**Drive-by evidence from the 2026-07-30 G7/G13 probe run** (a 40-model random export sample on
`se-thoughtspot`, gathered incidentally — none of it closes a verification, and all four stay open):

- **V1 is narrowed, not closed.** `properties.calendar` was present on 36 Model columns across
  12 models, and in *every* case the value was the bare lowercase token `calendar` — never
  `default`, and never `CALENDAR_TYPE_GREGORIAN`. That is consistent with the
  `calendar_name` reading and inconsistent with the SQL-View reference's enum-like spelling, but
  it did **not** settle the vocabulary, and no `calendar:` value was observed on a **Table**
  column. *(Both of the gaps in this bullet were closed by the census below.)*
- **V2 gained no evidence.** All 29 observed `currency_type` blocks used `iso_code` only; the
  `column` and `is_browser` forms did not appear in the wild, so the round-trip question is untouched.
- **V4 gained no evidence.** `is_mandatory_token_filter` appeared on zero columns in the sample.
- **`model.lesson_plans` shape is confirmed** (BL-186 step 4, the provisional one). Observed on 4
  real Models as a sibling of `properties:`, exactly as documented: a list of
  `{lesson_id: <int>, lesson_plan_string: <string>}` — e.g.
  `{"lesson_id": 0, "lesson_plan_string": "What were [Sales] by [Store Region] in [Date].'last year' ?"}`.
  The reference's provisional marker can be dropped.

**Superseding evidence — the 2026-07-30 TML property census.** A read-only census of **500**
logical-table TML documents on `se-thoughtspot` (143 Models, 275 Tables, 42 Views, 40 SQL Views,
sampled from a 15,204-object population; nothing created, modified or deleted) went further than
the 40-model sample above and **advanced V1, V2 and V3 past the positions recorded in those
bullets**. The V-item rows in the table above now carry the census position; the bullets are kept
because they record what was known when, and because the census contradicts one of them directly.
The four headline corrections:

1. **V1 — the census observes both of the things the 40-model sample reports as absent.** Two real
   *named* calendars on Model columns (`SeanTSCROOTS`, `Dupont_Fiscal_Cal`) **and** a `calendar:`
   on a **Table** column (`FACT_RETAPP_SALES.RECORDDATE: SeanTSCROOTS`). The `calendar_name`
   reading is therefore confirmed directly rather than inferred, and the Table-column half of V1 is
   answered **yes**. `CALENDAR_TYPE_GREGORIAN`: zero sightings in 500 documents, including zero on
   the SQL Views where our own reference claimed it.
2. **V2 — the `column` form exists**, on a Table column, as a bare column name.
3. **V3 — custom maps are in production**, 3 Models / 7 columns.
4. **V4 — a second and far larger sample still finds nothing.** Zero of 500 documents.

Two further census findings changed this document outside the V-items: the join-shape enum was
closed at two values but 12 of 493 real joins are **hybrids** (see `RelationshipLevel.join_shape`),
and `action_object_associations[]` was a wholly undocumented model-level construct (now a stash
key). The census also confirmed several existing claims empirically rather than by inference:
`db_column_name` on 2,719 of 2,719 Table columns (**R1**), `name` as the only key in all 313
connection blocks, `list_choice[]` objects in 79 of 79 parameters with `CHAR` ×24 / `VARCHAR` ×0
(**I10**), `column_id` in the `TABLE::col` form universally, and `formula_` + name as the
`formula_id` convention universally.

**What the census could not see, by construction.** It exported without `--fqn`, `--associated` or
`--include-obj-id`, so the `fqn` / `obj_id` / `destination.fqn` paths are absent from it *by
method*, not by absence in the product. **NM1** and **X8** — the identity rules — are therefore the
least-evidenced part of this document, and a re-run with those flags is the way to close that. Nor
can an export-only census speak to any *round-trip* question (V2's and V4's remaining halves), or
to any query-time semantic.

Absence from our TML references is not evidence a property does not exist: those references were
built from real import failures, so they are complete on *what breaks* and incomplete on *what is
merely optional*. That is the blind spot this table exists to track.

---

## Worked shape

One dataset, one attribute, one metric — the minimum that exercises the 1 + N document
split, the identifier rules, and the metric-as-formula rule ([**R4**](#reverse-direction-rules-ossie--tml)) — plus one deliberate
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
consumes it, per [**X9**](#protocol) nothing can stash it, so the converter raises an issue naming the
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

ThoughtSpot, Model document (no `guid` — [**R2**](#reverse-direction-rules-ossie--tml)):

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
