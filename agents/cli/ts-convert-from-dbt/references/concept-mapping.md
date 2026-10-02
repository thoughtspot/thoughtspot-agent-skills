# Concept Mapping — dbt → ThoughtSpot

This skill has **two paths**, and they translate in different places. Getting
this distinction right is the single most important thing on this page.

| Path | Who builds the Tables | Who builds the Model | When |
|---|---|---|---|
| **Path N** — `ts dbt generate-tml` / `generate-sync-tml` | ThoughtSpot, server-side | ThoughtSpot, server-side | Default. Works when the directory's FK graph is one connected component |
| **Path Y** — `generate-tml --import-worksheets NONE` + `ts dbt build-model` | ThoughtSpot, server-side | **This skill, client-side** (`ts_cli/dbt_build_export.py::build_model_tml_from_manifest`, `ts_cli/dbt_metricflow.py`) | Multi-fact directories, where ThoughtSpot's connected-component algorithm splits one directory into several Models (open-items #11), and any case needing MetricFlow metrics or `ts_rls_rules` |

So the older framing — "this skill only drives ThoughtSpot's translator" — is
true of the **Tables** on both paths and of the **Model** on Path N only. On
Path Y the Model TML is assembled locally from the compiled `manifest.json` +
`catalog.json` and imported with `ts tml import`, which is why several rows
below say "this skill, client-side."

---

## Connection and scope

| dbt construct | ThoughtSpot object | Who controls the mapping | Notes |
|---|---|---|---|
| dbt Cloud project (URL + account ID + project ID [+ env ID]) | dbt connection object (`dbt_connection_identifier`) | This skill (`ts dbt create`) | One connection per dbt project. `import_type: DBT_CLOUD`. Coordinates are persisted locally in a `ts profiles --platform dbt-cloud` profile — ThoughtSpot's `dbt/search` never echoes them back (open-items #4) |
| dbt Core `manifest.json` + `catalog.json` (zipped) | dbt connection object (`dbt_connection_identifier`) | This skill (`ts dbt create`) | `import_type: ZIP_FILE`. Re-uploaded on every `generate-tml`/`generate-sync-tml` call — not stored server-side between calls |
| dbt Cloud job run | The manifest/catalog every later step reads | This skill (`ts dbt trigger-job`) | `schema.yml` edits reach ThoughtSpot only once a job has compiled them into the artifacts. Polls to completion and prints the failed step's log tail on error |
| Directory of dbt models (`original_file_path` parent) | One `--model-tables` entry → one or more Tables + Model(s) | This skill selects the scope; ThoughtSpot generates the content | `model_tables` is **directory-grouped**, not per-file (open-items #11, #6) |
| model's materialised relation (`alias`, else `name`) | The `tables[]` names inside a `--model-tables` entry | This skill (extracted from `manifest.json`) | Must be the **alias** where one is set — a name-only entry 400s with "table(s) not found for model …" (live 2026-09-09). `ts dbt list-models` currently emits `name`, not `alias` — see open-items #15 |
| `import_worksheets` selection (ALL/NONE/SELECTED) | Whether/which Model is generated server-side | This skill (`ts dbt generate-tml --import-worksheets`) | Legacy field name — controls **Model** generation, not a Worksheet (open-items #1). `NONE` is Path Y's Tables-only first leg |

## Model content

| dbt construct | ThoughtSpot object | Who controls the mapping | Notes |
|---|---|---|---|
| model SQL body / column expressions | Table columns + Model formulas | ThoughtSpot, server-side | Only visible to this skill via `--include-semantic-report` (Snowflake/Databricks connections only — open-items #2). This skill neither performs nor verifies that SQL → formula translation |
| dbt model description / column `description:` | Table/Model description fields | ThoughtSpot server-side (Path N) **and** this skill (Path Y) | Verified live 2026-09-01 on the server-side path (`STG_PAYMENTS` column description landed); Path Y reads `columns[].description` from the manifest directly |
| Column `meta.ts_*` tags (`ts_column_type`, `ts_aggregation`, `ts_synonym`, `ts_format_pattern`, `ts_index_type`, `ts_index_priority`, `ts_attr_dim`, `ts_additive`, `ts_spotiq_pref`, `ts_hidden`, `ts_currency_type`, `ts_calendar_type`, `ts_geo_config`) | Column properties on the generated Table/Model | ThoughtSpot, server-side | ThoughtSpot's own documented tag set (docs.thoughtspot.com/cloud/26.8.0.cl/dbt-integration-metadata-tags, 2026-08-27). `ts_column_type`/`ts_aggregation`/`ts_synonym` + `description` verified live on manifest v12 (open-items #11); the rest unverified |
| Column `meta.ts_ai_context` | Column `properties.ai_context` | This skill, client-side (`build-model`) | Read from the manifest by `build_model_tml_from_manifest`. **Not** in ThoughtSpot's documented tag list — treat as a ts-cli extension until the server-side path is verified (open-items #16) |
| Column `meta.ts_display_name` | Model column display name | This skill, client-side (`build-model`) | ts-cli extension. Overrides `--pretty-names` and the physical name. Never read by server-side `generate-tml` |
| Column `meta.ts_column_exclude` | Column left out of the Model's `columns[]` entirely | This skill, client-side (`build-model`) | ts-cli extension. The column still exists on the Table (Tables are generated server-side). Distinct from `ts_hidden`, which keeps it in the Model |
| Column `meta.ts_formula` | Model `formulas[]` entry + a `formula_id` column | This skill, client-side (`build-model`) | The return leg of `ts-convert-to-dbt`'s formula round-trip — the ThoughtSpot expression is restored verbatim |
| Column declared with **no** `ts_*` meta, or present only in `catalog.json` | Column typed from the warehouse type | This skill, client-side (`build-model`, `infer_column_meta`) | Numeric → `MEASURE`/`SUM`; anything else, any MetricFlow entity/dimension column, and any `_ID`/`_KEY`/`_CODE`/`_NUMBER`-suffixed name → `ATTRIBUTE`. Reported on stderr, never silent |
| `relationships` data test + `ts_join_cardinality`/`ts_join_type`/`ts_join_name` under its `config.meta` | `model_tables[].joins[]` (name, `on`, type, cardinality) | ThoughtSpot server-side (Path N) **and** this skill (Path Y) | The only construct that can express join type/cardinality/name at all. Path Y reads the compiled test nodes (`resource_type == "test"`, `test_metadata.name == "relationships"`) |
| Model-level `config.meta.ts_rls_rules` | `rls_rules` on the **Table** TML | This skill, client-side (`build-model`) | RLS lives on the Table, not the Model, and server-side `generate-tml` does not process this tag. `build-model` exports each affected Table TML, patches `rls_rules` in, and re-imports (`extract_model_rls_from_manifest`). `generate-sync-tml` leaves existing `rls_rules` untouched, so a resync preserves them |

## dbt Semantic Layer (MetricFlow)

| dbt construct | ThoughtSpot object | Who controls the mapping | Notes |
|---|---|---|---|
| `metrics:` of type `simple` / `ratio` / `derived` (v2 nested `semantic_model:` spec) | Model `formulas[]` + MEASURE formula columns | This skill, client-side (`ts_cli/dbt_metricflow.py::translate_metrics`) | Metric `label` → display name; `description` and `config.meta.ts_*` → column properties. A metric whose label matches a `ts_formula` column supersedes it. Definition-level only — ThoughtSpot never queries the Semantic Layer |
| `metrics:` of type `cumulative` / `conversion`, metric-level `filter`s, `offset_window`/`offset_to_grain`, SQL-expression `expr`, `median`/`percentile`/`sum_boolean` aggs | **Not translated** | — | Each is reported on stderr with a reason, never dropped silently (open-items #14) |
| MetricFlow `entities` (foreign → primary/unique pair) | `model_tables[].joins[]` — `LEFT_OUTER` / `MANY_TO_ONE` | This skill, client-side (`dbt_metricflow.entity_joins`) | **Fallback only.** Emitted for a table pair that no `ts_join_*` `relationships` test already covers, so explicit tags keep authority over join type and name. Reported on stderr |
| ThoughtSpot's own server-side MetricFlow importer | — | ThoughtSpot | Tested live 2026-09-08 across three connections and both the REST and UI flows: 0 formulas, empty `semantic_report`, every spec version. The client-side translator above is currently the only path that works (open-items #14) |

## Not verified

| dbt construct | Status |
|---|---|
| dbt sources | UNVERIFIED — open-items #3 |
| dbt tests (other than `relationships`) | UNVERIFIED — open-items #3 |
| dbt exposures | UNVERIFIED — open-items #3 |
| dbt snapshots / seeds | UNVERIFIED — open-items #3 |

---

**Relationship to `ts-convert-to-dbt`.** That skill is the pure translator in
the opposite direction — it parses Model + Table TML and writes the `ts_*`
tags, `relationships` tests and `ts_formula`/`ts_rls_rules` entries this page
describes reading. There is no client-side **SQL**-translation reference file
(no `ts-dbt-formula-translation.md`) in either direction: formulas round-trip
verbatim through `ts_formula` rather than being rewritten as SQL, and
MetricFlow metrics are translated from their *structured* definition, not from
SQL text.
