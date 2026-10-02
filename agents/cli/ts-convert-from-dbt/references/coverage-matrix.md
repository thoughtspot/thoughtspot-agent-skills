# Coverage Matrix: dbt → ThoughtSpot Tables + Model

What `ts-convert-from-dbt` maps and what it does not.

**Two paths, two translators.** Tables are always generated inside
ThoughtSpot's servers (`ts dbt generate-tml` / `generate-sync-tml`). The
**Model** is generated server-side on Path N, but assembled **client-side** by
`ts dbt build-model` on Path Y (multi-fact directories, MetricFlow metrics,
`ts_rls_rules`). Rows below say which. See
[concept-mapping.md](concept-mapping.md) for the full construct-by-construct
detail behind each row.

---

## Mapped Constructs

| # | dbt Construct | ThoughtSpot Equivalent | Notes |
|---|---|---|---|
| 1 | dbt Cloud project (URL + account ID + project ID [+ env ID]) | dbt connection object (`dbt_connection_identifier`) | Verified live 2026-09-01 |
| 2 | dbt Core `manifest.json` + `catalog.json` (zipped) | dbt connection object, `import_type: ZIP_FILE` | Confirmed via REST API spec; ZIP_FILE path deliberately deferred from live testing (see `DBT_SYNC_PROGRESS.md` 2026-08-30 prioritization note). As of v0.133.0 every `--file` flag accepts the `target/` directory and builds the archive — zipping is no longer a user step (row 22) |
| 22 | The `target/` directory `dbt docs generate` writes | An upload-ready ZIP, built by the CLI | v0.133.0 — `--file` on `create`/`update`/`generate-tml`/`generate-sync-tml` accepts `target/`, the project root, either artifact, or a ready-made `.zip`. A missing `catalog.json` is **refused** naming `dbt docs generate`, because ThoughtSpot types Table columns from it and a manifest-only archive imports successfully with no column types. **Archive layout assumed flat at the root** — the literal reading of ThoughtSpot's "a ZIP containing manifest.json and catalog.json", not verified against a live ZIP_FILE connection (L6) |
| 3 | Directory of dbt models, selected via `--model-tables` | ThoughtSpot Tables + Model(s) | `model_tables` is directory-grouped, not per-file; `tables[]` must carry the materialised **alias**. Verified live 2026-09-01 (open-items #11) |
| 4 | Resync after a dbt project changes (`generate-sync-tml`) | Refreshed Table/Model TML | Verified live 2026-09-01, idempotent (same GUIDs). Fails on a Model carrying ThoughtSpot-only structural additions — open-items #12 |
| 5 | Per-model SQL → ThoughtSpot formula breakdown (`include_semantic_report`) | Per-component import/skip report | Snowflake and Databricks connections only. Returned empty on every live run so far (no formula columns to translate) |
| 6 | Model generation scope (`import_worksheets`: ALL / NONE / SELECTED) | Whether/which Model is generated server-side | Legacy field name — produces a Model, not a Worksheet. `NONE` is Path Y's Tables-only first leg |
| 7 | Column `meta.ts_*` tags — all 13 in ThoughtSpot's documented set | Column properties on the generated Table/Model | Tag set per docs.thoughtspot.com/cloud/26.9.0.cl/dbt-integration-metadata-tags (2026-09-09). Server-side on Path N; all 13 also read client-side by `build-model`. `ts_column_type` / `ts_aggregation` / `ts_synonym` verified live on dbt-fusion manifest v12 (2026-08-30, open-items #11); the other ten documented but not individually verified against the server-side sync. `ts_currency_type` and `ts_geo_config` take a NESTED block with a `type:` discriminator, not a flat value — see SKILL.md Step 5.5 |
| 8 | dbt column `description:` | Table/Model column description | Verified live 2026-09-01 server-side; also read client-side by `build-model` |
| 9 | `relationships` test + `ts_join_cardinality`/`ts_join_type`/`ts_join_name` under `config.meta` | `model_tables[].joins[]` | Server-side on Path N (verified on `models/marts/core`, 2026-09-01); client-side on Path Y (verified on 7-table barbershop incl. chasm joins, 2026-09-04) |
| 10 | Multi-fact directory (2+ FK-disconnected fact tables sharing dimensions) | ONE unified Model via `ts dbt build-model` (Path Y) | ThoughtSpot's server-side algorithm emits one Model per connected component instead — verified 2026-09-04. Path Y reads the compiled `ts_join_*` tests and assembles a single Model TML (open-items #11, ts-convert-to-dbt open-items #11) |
| 11 | Model-level `config.meta.ts_rls_rules` | `rls_rules` on the **Table** TML | Client-side, `ts dbt build-model` only — it exports each affected Table TML, patches `rls_rules` in, and re-imports (`extract_model_rls_from_manifest`). Server-side `generate-tml` does not process this tag; `generate-sync-tml` leaves existing `rls_rules` untouched, so a resync preserves them. Verified live 2026-09-09 |
| 12 | Column `meta.ts_formula` | Model `formulas[]` + a `formula_id` column | Client-side, `build-model` only. Return leg of `ts-convert-to-dbt`'s formula round-trip — expression restored verbatim. 14 formulas verified on export 2026-09-09 |
| 13 | Column `meta.ts_display_name` | Model column display name | **ts-cli extension**, `build-model` only. Overrides `--pretty-names` and the physical name |
| 14 | Column `meta.ts_column_exclude` | Column omitted from the Model's `columns[]` | **ts-cli extension**, `build-model` only. Column remains on the Table; distinct from `ts_hidden`. Verified live 2026-09-08 |
| 15 | Column `meta.ts_ai_context` | Column `properties.ai_context` | **ts-cli extension** — a gap filed with ThoughtSpot that has not shipped as a native tag (confirmed 2026-09-09, open-items #16), so the server-side sync does not read it. Both `build-model` commands do. 5 verified on export 2026-09-09 |
| 16 | Column with no `ts_*` meta, or present only in `catalog.json` | Column typed from the warehouse type | Client-side, `build-model` (`infer_column_meta`): numeric → MEASURE/SUM; otherwise, and for any MetricFlow entity/dimension column or `_ID`/`_KEY`/`_CODE`/`_NUMBER`-suffixed name → ATTRIBUTE. Listed on stderr |
| 17 | MetricFlow `metrics:` — `simple`, `ratio`, `derived` (v2 nested spec) | Model `formulas[]` + MEASURE formula columns | Client-side, `ts_cli/dbt_metricflow.py`. Verified live 2026-09-08 (6/6 barbershop metrics, 0 unmapped). Handles both dbt Cloud and dbt Fusion manifest dialects |
| 18 | MetricFlow `entities` (foreign → primary/unique pair) | `model_tables[].joins[]`, LEFT_OUTER / MANY_TO_ONE | Client-side **fallback only** — emitted for a table pair no `ts_join_*` test covers, so explicit tags keep authority. Reported on stderr. Verified live 2026-09-08 on a MetricFlow-only directory |
| 19 | dbt Cloud job run (compiling `schema.yml` into the artifacts) | Prerequisite for every row above on a DBT_CLOUD connection | `ts dbt trigger-job` triggers and polls to completion, printing the failed step's log tail on error. Verified live 2026-09-08 |
| 20 | Directory pre-check — is this a Path N or Path Y directory? | `ts dbt inspect --model-path` | Read-only manifest scan (v0.133.0): models, `ts_join_*` tests, `ts_rls_rules` models, MetricFlow metrics, and a `recommended_path` of `"Y"` if any of the last three is non-empty, with `reasons[]` naming each signal. Uses the SAME scan predicates as `build_model_tml_from_manifest`, asserted by `TestTsJoinTests::test_agrees_with_the_reader_that_consumes_it` — so it cannot recommend Path Y for a join graph `build-model` will not find |
| 21 | A local `manifest.json` / `target/` dir / project ZIP as the artifact source | `--manifest` on `ts dbt list-models` and `ts dbt inspect` | v0.133.0 — the ZIP_FILE / offline path, needing no dbt Cloud profile, token or network. Closes the "these two commands are dbt Cloud only" half of L6 for *reading* the manifest; `build-model` and `trigger-job` remain dbt Cloud only |

---

## Unmapped Constructs (Limitations)

### Not verified — needs live-instance or deeper-docs confirmation

| # | dbt Construct | Limitation | Notes |
|---|---|---|---|
| L1 | dbt sources | Whether sources import as Tables alongside models | Not verified — see open-items.md #3 |
| L2 | dbt tests other than `relationships` | Whether tests are surfaced anywhere in ThoughtSpot | Not verified — see open-items.md #3 |
| L3 | dbt exposures | Whether exposures are surfaced anywhere in ThoughtSpot | Not verified — see open-items.md #3 |
| L4 | dbt snapshots / seeds | Whether snapshots/seeds are treated as models or excluded | Not verified — see open-items.md #3 |
| L5 | All five ts-cli extension tags on the server-side path | `generate-tml`/`generate-sync-tml` read none of them | `ts_formula`, `ts_display_name`, `ts_ai_context`, `ts_column_exclude`, `ts_rls_rules` are honoured only by the client-side `build-model` commands, so a **Path N** import drops them silently. Not a defect — they are this toolchain's own tags (open-items #16) |
| L6 | ZIP_FILE path, end to end | No live run against a dbt Core project | Deliberately deferred 2026-08-30 in favour of the DBT_CLOUD path. Narrowed in v0.133.0: `list-models` and `inspect` now read a local manifest via `--manifest` (row 21), so the *reading* half has a ZIP_FILE path. `ts dbt build-model` and `ts dbt trigger-job` remain **dbt Cloud only** — the offline return leg is `ts dbt-export build-model --model-guid --import` |

### DEFERRED — reported, not translated

| # | dbt Construct | Limitation | Notes |
|---|---|---|---|
| L7 | MetricFlow `cumulative` / `conversion` metrics | No ThoughtSpot formula emitted | Reported on stderr with a reason — see open-items.md #14 |
| L8 | MetricFlow metric-level and input-metric `filter`s, `offset_window` / `offset_to_grain` | No ThoughtSpot formula emitted | Conditional aggregation is the next translatable shape — open-items.md #14 |
| L9 | MetricFlow simple metric with a SQL-expression `expr` (not a bare column) | No ThoughtSpot formula emitted | Would need `sv_translate`-style SQL translation — open-items.md #14 |
| L10 | MetricFlow `median` / `percentile` / `sum_boolean` aggregations | No ThoughtSpot aggregate equivalent | Reported unmapped |

### HIGH — no workaround within this integration

| # | dbt Construct | Reason | Notes |
|---|---|---|---|
| L11 | ThoughtSpot's own server-side MetricFlow importer | Produces nothing on the tested instance | Tested live 2026-09-08 across three connections (v2 nested, hand-converted legacy, and dbt-Cloud-compiled legacy), via both REST and the Data-workspace UI: 0 formulas, empty `semantic_report`, numeric columns not even typed as measures. The client-side translator (row 17) is the only working path — open-items.md #14 |
| L12 | Non-certified warehouse (not Redshift/Databricks/BigQuery/Snowflake) | ThoughtSpot's dbt integration is certified only for these four | Enforcement point (create-time vs. generate-time) not verified — see open-items.md #5 |
| L13 | Enumerating a connection's available dbt models from ThoughtSpot | No ThoughtSpot API for this | The skill sources the list itself: `manifest.json` parse (ZIP_FILE) or `ts dbt list-models`, which pulls the latest successful run's `manifest.json` from the dbt Cloud Admin API (DBT_CLOUD) — see open-items.md #4 |
| L14 | Predicting what `generate-sync-tml` will change before running it | No dry-run or diff response on this endpoint | SKILL.md Steps 10.1–10.5 build a best-effort preflight/post-hoc check around this gap — see open-items.md #7 |
| L15 | Resyncing a Model that carries ThoughtSpot-only **structural** additions | `generate-sync-tml` returned HTTP 500 | Metadata-only enrichment (descriptions, synonyms, column types) round-trips cleanly — verified 2026-09-01. Formula columns / extra physical columns dbt does not know about are the suspected trigger — see open-items.md #12 |
| L16 | Updating a Path Y Model's **join graph** via `generate-sync-tml` | The resync refreshes Tables and columns only | Re-run `ts dbt build-model --model-guid …` (or `ts dbt-export build-model` + `ts tml import`) afterwards — SKILL.md Step 10.4 |
