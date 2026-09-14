# Concept Mapping — ThoughtSpot → dbt

Unlike `ts-convert-from-dbt` (whose Path N hands the work to ThoughtSpot's
server-side translator), this direction has no native ThoughtSpot API — this
skill *is* the translator. Every row below is either emitted deterministically
or explicitly reported as skipped/unmapped; nothing is silently dropped.

Two commands, two directions of travel:

| Command | Module | Direction |
|---|---|---|
| `ts dbt-export build` (Case A) / `diff` + `sync` (Case B) | `dbt_build_export.py::build_dbt_export`, `dbt_diff.py` | Model + Table TML → dbt project files |
| `ts dbt-export build-model` | `dbt_build_export.py::build_model_tml_from_schema_yml` | `schema.yml` → a unified Model TML (the return leg — see the last section) |

---

## Project structure

| ThoughtSpot construct | dbt construct | Notes |
|---|---|---|
| Model `model_tables[]` — distinct physical table | One staging dbt model (`select * from {{ source(...) }}`) at `models/staging/<name>.sql` | One `.sql` file per distinct `(database, schema, table)`. Default name `stg_<table>`; Case B adopts the existing project's name instead (see below) |
| Model `model_tables[]` — role-play alias of an already-staged table | Thin passthrough model (`select * from {{ ref(...) }}`) at `models/marts/dim_<alias>.sql` | Preserves the alias as its own dbt model rather than collapsing it |
| Table's `(database, schema)` | One `sources:` entry in `models/staging/sources.yml` | A Model spanning several locations gets one entry per distinct `(database, schema)` pair — dbt puts `database:`/`schema:` at the source level, not per table. Multi-location projects get suffixed names (`<source>_1`, `<source>_2`) |
| — | `dbt_project.yml` | Minimal Case A scaffold only (`name`, `version`, `config-version`, `profile`, `model-paths`, `clean-targets`) |
| An existing dbt model that already selects from, **or produces**, one of the Model's tables | That model's own name is reused instead of `stg_<table>` | Case B only (`adopted_names` in the `diff`/`sync` output). Matched by `{{ source() }}` on `(DATABASE, SCHEMA, TABLE)`, or by the Table's `db_table` equalling a dbt model name — the shape `ts-convert-from-dbt` produces, reported as `dbt_output_tables` |

## Column properties → `ts_*` tags (`models/schema.yml`, the primary artifact)

All of these land under the column's `config: {meta: {...}}`.

| ThoughtSpot construct | dbt construct | Notes |
|---|---|---|
| Column `properties.column_type` | `ts_column_type` (`attribute`/`measure`) | |
| Column `properties.aggregation` | `ts_aggregation` | Lower-cased |
| Column `properties.synonyms` | `ts_synonym` | Comma-joined; a synonym equal to the display name is dropped |
| Column `properties.format_pattern` | `ts_format_pattern` | |
| Column `properties.index_type` | `ts_index_type` (`DEFAULT`→`default`, `DONT_INDEX`→`dont_index`) | Any other value is reported unmapped — see [open-items.md](open-items.md) #12 for whether the case-folding is needed at all |
| Column `properties.index_priority` | `ts_index_priority` | |
| Column `properties.is_attribution_dimension` | `ts_attr_dim` (`yes`) | Emitted only when true |
| Column `properties.is_additive` | `ts_additive` (`yes`) | Emitted only when true |
| Column `properties.spotiq_preference` | `ts_spotiq_pref` (`exclude`) | Emitted only for `EXCLUDE` |
| Column `properties.is_hidden` | `ts_hidden` (`yes`) | Emitted only when true |
| Column `properties.calendar` | `ts_calendar_type` | Calendar **name**, verbatim. Connection-scoped, so it means nothing on an instance whose connection has no calendar of that name |
| Column `properties.currency_type` | `ts_currency_type` — a **nested block** with a `type` discriminator | `{iso_code: USD}` → `{type: from_isocode, isocode: USD}`; `{column: CCY}` → `{type: from_column, column: CCY}`; `{is_browser: true}` → `{type: from_browser}` |
| Column `properties.geo_config` | `ts_geo_config` — a **nested block** with a `type` discriminator | `{latitude: true}` → `{type: latitude}`; `{longitude: true}` → `{type: longitude}`; `{country: true}` → `{type: country}`; `{region_name: {country: C, region_name: R}}` → `{type: sub_nation_region, country: C, region_type: R}` |
| Column `properties.geo_config` — custom-map role (`custom_file_guid` + `geometryType`) | **Not emitted** — reported in `unmapped_properties` | The one geo role with no `ts_geo_config` type. `thoughtspot-model-tml.md` also calls it instance-local: "a portable document must not carry it — the geo role has to be dropped rather than translated" |
| Column `properties.ai_context` | `ts_ai_context` | **ts-cli extension** — a gap filed with ThoughtSpot that has not shipped natively, so the server-side sync does not read it (confirmed 2026-09-09, [ts-convert-from-dbt open-items](../../ts-convert-from-dbt/references/open-items.md) #16) |
| Column `name` (Model display name) | `ts_display_name` | **ts-cli extension.** Emitted only when the display name is *not* derivable from the physical column — i.e. it differs from the raw name, its prettified form, and the `<TABLE>_<COL>` dedupe form `build-model` would produce. Otherwise omitted, so the file stays quiet |
| Column `description` | dbt column `description:` | A plain dbt field, not a `ts_*` tag |
| Formula (calculated) column | `ts_formula` under `config.meta`, expression preserved **verbatim**, plus `ts_column_type`/`ts_aggregation`/`ts_synonym`/`ts_index_type`/`ts_ai_context` and the column `description:` | Placed on the dbt model matching the **first** `[TABLE::COLUMN]` reference in the expression (`_first_table_ref`). Round-trip verified 2026-09-09 — see [open-items.md](open-items.md) #3 |
| Formula column whose expression has **no** `[TABLE::COL]` reference | **Not emitted** — reported in `skipped_formulas` | e.g. `sum(x)`. There is no model to attach it to |

## Joins

| ThoughtSpot construct | dbt construct | Notes |
|---|---|---|
| Single-column join (`model_tables[].joins[]`) | A `relationships` data test on the FK column, with `ts_join_cardinality`/`ts_join_type`/`ts_join_name` under the test's `config.meta` and `severity: warn` | Primary artifact — the only place join cardinality/type/name is carried forward at all |
| Single-column join | A MetricFlow entity pair (foreign entity on the FK table, primary entity on the PK table, matched by name) in `models/semantic_models.yml` | Secondary, optional artifact. Entities are pure identity — no cardinality, type or name |
| Join `cardinality` / `type` outside ThoughtSpot's `one_to_one`/`many_to_one`/`one_to_many` and `inner`/`left_outer`/`right_outer`/`full_outer` | **Not emitted** for that field — reported in `unmapped_properties` | The rest of the test is still emitted |
| Composite-key join (2+ columns) | **Not emitted** in either artifact — reported in `skipped_composite_joins` | dbt's own `relationships` test is single-column too; see [open-items.md](open-items.md) #5 |

## Security

| ThoughtSpot construct | dbt construct | Notes |
|---|---|---|
| Table TML `rls_rules` | `ts_rls_rules` under the **model-level** `config.meta` in `schema.yml` — a list of `{name, expr, table_paths}`, each `table_paths` entry `{id, table, columns}` | RLS lives on the Table TML, not the Model. `table_paths[].column` (TML) becomes `columns` (schema.yml); the TML's top-level `tables` list is derivable on read-back and so not stored. Applied back by `ts dbt build-model` — see the return-leg section |
| Column Security Rules (CSR) | **Not emitted** | CSR is not part of Table TML at all; it lives behind `security/column/fetch`. See [open-items.md](open-items.md) #13 |

## MetricFlow (`models/semantic_models.yml`, the secondary artifact)

| ThoughtSpot construct | dbt construct | Notes |
|---|---|---|
| Column classified as dimension | `dimensions:` entry, `type: categorical` | |
| Column classified as a time dimension (date-typed) | `dimensions:` entry, `type: time`, `time_granularity: day` | |
| Column classified as a measure | `measures:` entry (agg defaulting to `sum`) **and** a matching `metrics:` entry of `type: simple` | No date-dimension prerequisite — every measure column produces both |
| — | Nothing at all for a table with no entities and no classified columns | An empty semantic model is not useful, and dbt's classic spec requires `entities` |

This artifact targets the **legacy** top-level `semantic_models:`/`metrics:`
spec, not dbt's current nested one — see [open-items.md](open-items.md) #2 for
why, and for the fact that ThoughtSpot's own MetricFlow importer has never been
shown to read it.

## Not emitted

| ThoughtSpot construct | Reason |
|---|---|
| Column `properties.geo_config` — custom-map role only | No `ts_geo_config` type exists for it, and it is instance-local — reported in `unmapped_properties` |
| Column `properties.index_type` outside `DEFAULT`/`DONT_INDEX` | `ts_index_type` documents only those two of TML's five values — reported in `unmapped_properties` |
| Column `properties.value_casing`, `custom_order`, `default_date_bucket`, `search_iq_preferred`, `synonym_type` | Real TML column properties with **no `ts_*` tag at all** in ThoughtSpot's documented set — nothing to map to. Not currently reported either; see [open-items.md](open-items.md) #9 |

`is_hidden`, `calendar`, `currency_type` and `geo_config` were on this list
until 2026-09-09 and are now emitted — see [open-items.md](open-items.md) #9
for the reasoning (the schema doc's prohibitions are scoped to *generating* a
model; this exporter is the round-trip leg those same rows bless).

## The ts-cli extension tags

Five `ts_*` tags are **not** in ThoughtSpot's documented vocabulary
(docs.thoughtspot.com/cloud/26.9.0.cl/dbt-integration-metadata-tags). They are
this toolchain's own, they round-trip in both directions, and a user may edit
them on **either** side — in ThoughtSpot, or by hand in `schema.yml`.

| Tag | Level | Emitted by `build` from | Restored by | Server-side `generate-tml` |
|---|---|---|---|---|
| `ts_formula` | column | a formula column's expression, verbatim | both `build-model` commands | no |
| `ts_display_name` | column | the Model column's display name, when not derivable from the physical name | both `build-model` commands | no |
| `ts_ai_context` | column | `properties.ai_context` | both `build-model` commands | no — an unshipped product gap, not a native tag |
| `ts_column_exclude` | column | never — hand-authored only, no Model property means "omit from the Model" | both `build-model` commands (column omitted; also honoured by `diff`/`sync`) | no |
| `ts_rls_rules` | **model** | the Table TML's `rls_rules` | `ts dbt build-model` applies it by patching the Table TML; `ts dbt-export build-model --rls-out` writes the block for manual merge | no |

Two consequences worth stating plainly:

1. **Only Path Y is lossless.** All five are invisible to ThoughtSpot's
   server-side sync, so a return leg through `ts-convert-from-dbt` **Path N**
   drops every one of them without an error. Use Path Y
   (`ts dbt build-model`) whenever any are in play.
2. **`ts_rls_rules` is the one that needs a Table, not a Model.** RLS lives on
   the Table TML, so a Model-only command cannot apply it — see the return-leg
   table below.

## The return leg — `ts dbt-export build-model`

`build_model_tml_from_schema_yml` reads a `schema.yml` back and assembles a
single unified ThoughtSpot Model TML, reversing the tables above. It exists
because `ts dbt generate-tml` splits a multi-fact project into one Model per
FK-source (fact) table ([open-items.md](open-items.md) #11).

| dbt construct | ThoughtSpot construct | Notes |
|---|---|---|
| Each `models:` entry | A `model_tables[]` entry, `id`/`name` = the dbt model name upper-cased | Join targets outside the file are added too |
| `relationships` test + `ts_join_*` meta | `model_tables[].joins[]` | Defaults when the tags are absent: `many_to_one`, `left_outer`, `<SRC>_to_<TGT>` lower-cased |
| Column `config.meta` `ts_*` tags (or a legacy bare `meta:`) | Column `properties` — `column_type`, `aggregation`, `synonyms`, `format_pattern`, `index_type`, `ai_context` | Both YAML shapes are accepted on read |
| Column `ts_formula` | A `formulas[]` entry (`id` = `formula_<sanitised name>`) plus its `formula_id` column | Expression restored verbatim |
| Column `description` | Column `description` | |
| A physical column name appearing on 2+ tables | Display name prefixed `<TABLE>_<COL>` | Model column names must be unique; ThoughtSpot rejects the whole import otherwise |
| Model-level `ts_rls_rules` | A Table TML `rls_rules` block, via `extract_table_rls_from_schema_yml` | Returned per table for the caller to patch in. `ts dbt build-model` does this automatically from the compiled manifest (`extract_model_rls_from_manifest`); `ts dbt-export build-model` returns the Model TML only, so a new-environment RLS patch is still manual |

---

**The key structural difference from `ts-convert-from-dbt`:** that skill drives
ThoughtSpot's own translator for Tables (and, on Path N, the Model). This skill
is the translator, in the opposite direction — the same role
`ts-convert-to-snowflake-sv` plays for Snowflake Semantic Views. Formulas are
*not* rewritten as SQL in either direction; they round-trip verbatim through
`ts_formula`, which is why no `ts-dbt-formula-translation.md` reference exists
or is needed ([open-items.md](open-items.md) #3).
